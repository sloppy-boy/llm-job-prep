# Runtime Model Settings and Eval Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Provide persistent, front-end controlled primary-model routing with secure API-key handling and balance alerts, then raise the real 78-question evaluation to at least 90% through bad-case-first iteration.

**Architecture:** backend/.env is the sole persistent store for provider credentials and routes. A focused runtime-settings module parses, validates, atomically updates, and exposes a redacted view; the LLM layer resolves the active provider per call and invalidates cached clients after a successful save. The React workspace adds a settings modal and balance/model status controls, while a dataset-selectable evaluator enforces a 9-case regression gate before one full 78-question run.

**Tech Stack:** FastAPI, Pydantic Settings, python-dotenv, OpenAI Python SDK, httpx, pytest, Next.js 16, React 19, TypeScript, Vitest, Testing Library, Qdrant.

**Spec:** docs/superpowers/specs/2026-08-19-runtime-model-settings-and-eval-closure-design.md

## Global Constraints

- Persist provider configuration only in backend/.env, which remains gitignored; never stage it.
- Support exactly deepseek, siliconflow, and custom-openai as primary providers.
- Persist each provider's Key, Base URL, and default model independently so switching never erases another provider's configuration.
- Do not return, log, put in SSE frames, or render API keys, Authorization headers, or raw upstream error bodies.
- Keep the fallback fixed at SiliconFlow deepseek-ai/DeepSeek-V3; no fallback-model UI is in scope.
- All settings and balance endpoints remain behind the existing X-API-Key middleware.
- A failed validation, connection test, or .env write must preserve the prior active route.
- DeepSeek official balance may be queried; SiliconFlow and custom providers must report unsupported rather than inventing a balance.
- A balance/credit exhaustion signal disables sending; an unknown balance or ordinary network failure must not.
- Do not stage, alter, or delete the user-owned untracked backend/knowledge_base/backfill/ directory.
- Run only the 9-case regression dataset during optimization. Run all 78 questions exactly once only after the regression result is 9/9.
- Update README, CONTEXT, and resume-facing figures only if the real full result is at least 90%.

---

### Task 1: Runtime settings persistence and redacted provider registry

**Files:**
- Create: backend/app/runtime_settings.py
- Create: backend/tests/test_runtime_settings.py
- Modify: backend/app/config.py
- Modify: backend/.env.example

**Interfaces:**
- Produces ProviderConfig(id, label, base_url, api_key, model).
- Produces get_runtime_settings(), public_runtime_settings(), save_runtime_settings(payload), active_primary_config(), and reset_runtime_settings_cache().
- public_runtime_settings returns providers with label, baseUrl, model, hasKey; primary with provider/model; and balanceThreshold.

- [ ] **Step 1: Write failing settings tests**

~~~python
def test_public_settings_redacts_keys(monkeypatch, tmp_path):
    store = _store_at(tmp_path, monkeypatch, {
        "DEEPSEEK_API_KEY": "ds-secret",
        "SILICONFLOW_API_KEY": "sf-secret",
        "LLM_PRIMARY_PROVIDER": "siliconflow",
    })
    public = store.public_runtime_settings()
    assert public["providers"]["deepseek"]["hasKey"] is True
    assert public["providers"]["siliconflow"]["hasKey"] is True
    assert "secret" not in repr(public)

def test_save_keeps_empty_key_and_persists_other_provider(monkeypatch, tmp_path):
    store = _store_at(tmp_path, monkeypatch, {
        "SILICONFLOW_API_KEY": "old-sf-key",
        "DEEPSEEK_API_KEY": "old-ds-key",
    })
    store.save_runtime_settings({
        "providers": {"deepseek": {"apiKey": "", "model": "deepseek-chat"}},
        "primary": {"provider": "deepseek"},
        "balanceThreshold": 8.5,
    })
    values = dotenv_values(store.ENV_PATH)
    assert values["DEEPSEEK_API_KEY"] == "old-ds-key"
    assert values["SILICONFLOW_API_KEY"] == "old-sf-key"
    assert values["LLM_PRIMARY_PROVIDER"] == "deepseek"
    assert values["BALANCE_WARN_THRESHOLD"] == "8.5"
~~~

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: pytest backend/tests/test_runtime_settings.py -v  
Expected: FAIL because app.runtime_settings does not exist.

- [ ] **Step 3: Implement the provider registry and atomic .env writer**

~~~python
PROVIDER_FIELDS = {
    "deepseek": {"key": "DEEPSEEK_API_KEY", "url": "DEEPSEEK_BASE_URL", "model": "DEEPSEEK_MODEL"},
    "siliconflow": {"key": "SILICONFLOW_API_KEY", "url": "SILICONFLOW_BASE_URL", "model": "SILICONFLOW_MODEL"},
    "custom-openai": {"key": "CUSTOM_OPENAI_API_KEY", "url": "CUSTOM_OPENAI_BASE_URL", "model": "CUSTOM_OPENAI_MODEL"},
}

def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 http 或 https 地址")
    return value.rstrip("/")
~~~

Render existing non-managed lines plus one quoted line per changed managed key to a sibling NamedTemporaryFile, flush and fsync it, then use os.replace. Validate provider ID, primary model, and URL before writing. Empty apiKey preserves the existing key. Extend Settings and .env.example with DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL, custom provider fields, LLM_PRIMARY_PROVIDER, MODEL_PRIMARY, and BALANCE_WARN_THRESHOLD.

- [ ] **Step 4: Run focused settings tests and configuration import**

Run: pytest backend/tests/test_runtime_settings.py -v && python -c "from app.runtime_settings import public_runtime_settings; print(public_runtime_settings()['primary'])" from backend/  
Expected: PASS; command prints provider/model only.

- [ ] **Step 5: Commit**

~~~bash
git add backend/app/runtime_settings.py backend/app/config.py backend/.env.example backend/tests/test_runtime_settings.py
git commit -m "feat: add persistent runtime model settings"
~~~

### Task 2: Dynamic LLM clients and provider-balance state

**Files:**
- Create: backend/app/balance.py
- Modify: backend/app/llm.py
- Modify: backend/tests/test_llm.py
- Create: backend/tests/test_balance.py

**Interfaces:**
- Produces get_primary_client() -> tuple[OpenAI, ProviderConfig] and clear_client_cache() in app.llm.
- Produces classify_credit_error(status, body), record_credit_exhausted(provider), get_balance_status(force=False), and clear_balance_cache() in app.balance.
- get_balance_status returns provider, supported, state (ok/low/unavailable/unknown/unsupported), balance, threshold, checkedAt, and message.

- [ ] **Step 1: Write failing dynamic-client and balance tests**

~~~python
def test_primary_client_changes_after_runtime_route_save(monkeypatch):
    first_cfg = ProviderConfig("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "key-a", "deepseek-chat")
    second_cfg = ProviderConfig("siliconflow", "硅基流动", "https://api.siliconflow.cn/v1", "key-b", "deepseek-ai/DeepSeek-V4-Flash")
    monkeypatch.setattr(llm, "active_primary_config", lambda: first_cfg)
    llm.clear_client_cache()
    first, _ = llm.get_primary_client()
    monkeypatch.setattr(llm, "active_primary_config", lambda: second_cfg)
    second, cfg = llm.get_primary_client()
    assert cfg.id == "siliconflow"
    assert first is not second

def test_deepseek_low_balance_is_cached(monkeypatch):
    monkeypatch.setattr(balance, "active_primary_config", lambda: _deepseek_config())
    monkeypatch.setattr(balance.httpx, "Client", _client_returning({
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "2.30"}],
    }))
    result = balance.get_balance_status(force=True)
    assert result["state"] == "low"
    assert result["balance"] == 2.3
~~~

- [ ] **Step 2: Run focused tests to verify they fail**

Run: pytest backend/tests/test_llm.py backend/tests/test_balance.py -v  
Expected: FAIL because dynamic-client and balance interfaces do not exist.

- [ ] **Step 3: Implement dynamic primary selection and adapters**

~~~python
def get_primary_client() -> tuple[OpenAI, ProviderConfig]:
    cfg = active_primary_config()
    fingerprint = (cfg.id, cfg.base_url, cfg.api_key, cfg.model)
    if fingerprint not in _primary_clients:
        _primary_clients.clear()
        _primary_clients[fingerprint] = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    return _primary_clients[fingerprint], cfg
~~~

Replace fixed module-level primary client use in _retry with get_primary_client. Preserve three primary retries and the fixed SiliconFlow V3 fallback. Query DeepSeek only at baseUrl/user/balance, sum CNY total_balance, and cache the redacted result for 60 seconds. Mark SiliconFlow/custom unsupported. Treat HTTP 402 and bounded lowercased quota/balance phrases as unavailable; never keep raw upstream body.

- [ ] **Step 4: Run focused tests**

Run: pytest backend/tests/test_llm.py backend/tests/test_balance.py -v  
Expected: PASS without real provider calls.

- [ ] **Step 5: Commit**

~~~bash
git add backend/app/llm.py backend/app/balance.py backend/tests/test_llm.py backend/tests/test_balance.py
git commit -m "feat: support dynamic primary model and balance state"
~~~

### Task 3: Settings, connection-test, and balance HTTP APIs

**Files:**
- Create: backend/app/api/settings.py
- Modify: backend/app/main.py
- Modify: backend/app/api/chat.py
- Create: backend/tests/test_settings_api.py
- Modify: backend/tests/test_chat.py

**Interfaces:**
- Mounts GET/PUT /api/v1/settings, POST /api/v1/providers/{provider}/test, and GET /api/v1/balance.
- PUT accepts providers, primary, and balanceThreshold; it returns redacted settings.
- Provider test returns ok/provider/model/usage or an error that cannot contain a key.

- [ ] **Step 1: Write failing endpoint and safe-SSE tests**

~~~python
def test_settings_get_never_returns_api_key(monkeypatch):
    monkeypatch.setattr(settings_api, "public_runtime_settings", lambda: {
        "providers": {"siliconflow": {"hasKey": True, "model": "m", "baseUrl": "https://x"}},
        "primary": {"provider": "siliconflow", "model": "m"}, "balanceThreshold": 5.0,
    })
    body = TestClient(app).get("/api/v1/settings", headers=HEADERS).json()
    assert body["providers"]["siliconflow"]["hasKey"] is True
    assert "apiKey" not in repr(body)

def test_credit_exhaustion_emits_safe_sse_error(monkeypatch):
    monkeypatch.setattr(chat_mod, "run_front", lambda *args: _answerable_policy_state())
    monkeypatch.setattr(chat_mod, "llm_chat_stream", lambda _m: (_ for _ in ()).throw(CreditExhaustedError("secret-body")))
    body = TestClient(app).post("/api/v1/chat", headers=HEADERS, json=_request()).text
    assert "请在模型设置中切换供应商" in body
    assert "secret-body" not in body
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: pytest backend/tests/test_settings_api.py backend/tests/test_chat.py -v  
Expected: FAIL because the router and typed credit-aware SSE response do not exist.

- [ ] **Step 3: Implement router and safe chat error**

~~~python
@router.put("/settings")
def update_settings(req: SettingsUpdateRequest) -> dict:
    try:
        updated = save_runtime_settings(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clear_client_cache()
    clear_balance_cache()
    return updated
~~~

Connection test sends one non-streaming 16-token OpenAI-compatible completion using stored provider config and never saves configuration. In chat.py catch the typed credit-exhausted exception before generic Exception, record provider state, and emit one fixed SSE message that asks the user to switch supplier. Register the router in main.py.

- [ ] **Step 4: Verify APIs and backend suite**

Run: pytest backend/tests/test_settings_api.py backend/tests/test_chat.py -v && pytest backend/tests -q  
Expected: PASS and existing middleware behavior preserved.

- [ ] **Step 5: Commit**

~~~bash
git add backend/app/api/settings.py backend/app/main.py backend/app/api/chat.py backend/tests/test_settings_api.py backend/tests/test_chat.py
git commit -m "feat: expose model settings and balance APIs"
~~~

### Task 4: Front-end model settings and balance alerts

**Files:**
- Create: frontend/components/ModelSettingsModal.tsx
- Create: frontend/components/ModelStatus.tsx
- Modify: frontend/lib/api.ts
- Modify: frontend/app/page.tsx
- Modify: frontend/components/ChatWindow.tsx
- Create: frontend/tests/ModelSettingsModal.test.tsx
- Modify: frontend/tests/ChatWindow.test.tsx

**Interfaces:**
- Produces fetchRuntimeSettings, saveRuntimeSettings, testProviderConnection, and fetchBalanceStatus in frontend/lib/api.ts.
- ModelSettingsModal receives open, onClose, onSaved(settings); it never receives a stored API key.
- ModelStatus receives settings, balance, onOpenSettings.
- ChatWindow accepts optional sendingDisabled and disabledReason.

- [ ] **Step 1: Write failing UI tests**

~~~tsx
it("does not render an already stored API key and keeps blank key on save", async () => {
  render(<ModelSettingsModal open onClose={vi.fn()} onSaved={vi.fn()} />);
  await screen.findByText("硅基流动");
  expect(screen.getByPlaceholderText("已配置（留空保持不变）")).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({
    providers: expect.objectContaining({ siliconflow: expect.objectContaining({ apiKey: "" }) }),
  }));
});

it("disables sending only when balance is unavailable", () => {
  render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()}
      sendingDisabled disabledReason="当前供应商额度不足，请在模型设置中切换供应商" />);
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  expect(screen.getByText(/额度不足/)).toBeInTheDocument();
});
~~~

- [ ] **Step 2: Run focused UI tests to verify they fail**

Run: npm test -- --run tests/ModelSettingsModal.test.tsx tests/ChatWindow.test.tsx from frontend/  
Expected: FAIL because components and props do not exist.

- [ ] **Step 3: Implement settings modal, status badge, and send guard**

~~~tsx
const isExhausted = balance?.state === "unavailable";
<ModelStatus settings={settings} balance={balance} onOpenSettings={() => setSettingsOpen(true)} />
<ChatWindow
  sessionId={sessionId}
  onSources={setSources}
  onThinking={setThinking}
  sendingDisabled={isExhausted}
  disabledReason="当前供应商额度不足，请在模型设置中切换供应商"
/>
~~~

Poll balance on mount and every 60 seconds. Render normal, low, unavailable, unsupported, and unknown distinctly; only unavailable disables input/send. The modal must have DeepSeek, SiliconFlow, and custom OpenAI-compatible cards, primary selector, URL/model fields, blank password inputs with hasKey status, threshold, per-provider connection test, and save. After save use only the redacted response and re-fetch balance.

- [ ] **Step 4: Run all front-end tests and production build**

Run: npm test && npm run build from frontend/  
Expected: PASS with no TypeScript error and no API Key in rendered output.

- [ ] **Step 5: Commit**

~~~bash
git add frontend/components/ModelSettingsModal.tsx frontend/components/ModelStatus.tsx frontend/lib/api.ts frontend/app/page.tsx frontend/components/ChatWindow.tsx frontend/tests/ModelSettingsModal.test.tsx frontend/tests/ChatWindow.test.tsx
git commit -m "feat: add model settings and balance alerts UI"
~~~

### Task 5: Bad-case regression dataset and controlled evaluator

**Files:**
- Create: backend/eval/badcases.json
- Modify: backend/eval/judge.py
- Modify: backend/eval/questions.json
- Modify: backend/tests/test_eval_dataset.py
- Create: backend/tests/test_eval_runner.py

**Interfaces:**
- python -m eval.judge --dataset badcases.json evaluates only the named JSON file.
- load_dataset(path) validates a non-empty list with category, non-empty question, and non-empty expected_points.
- evaluate_items(items) is used by both regression and full CLI modes.

- [ ] **Step 1: Write failing dataset/runner tests**

~~~python
BADCASE_QUESTIONS = {
    "Type-C快充数据线有哪些长度？",
    "你能帮我写一篇5000字的毕业论文吗？",
    "订单20260811002最近的物流节点是什么？",
    "订单20260812003现在到哪一步了？",
    "已使用的商品申请七天无理由退货能退多少钱？",
    "人工客服的服务时间是什么时候？",
    "什么情况会转人工客服？",
    "我的订单20260811001商品破损了，退货运费谁承担？",
    "我的订单里有不认识的商品，怎么申请退款？",
}

def test_badcase_dataset_has_exactly_nine_known_failures():
    assert {x["question"] for x in judge.load_dataset(Path("eval/badcases.json"))} == BADCASE_QUESTIONS

def test_latest_logistics_expected_point_is_latest_state_only():
    item = next(x for x in judge.load_dataset(Path("eval/questions.json"))
                if x["question"] == "订单20260811002最近的物流节点是什么？")
    assert item["expected_points"] == ["运输中"]
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: pytest backend/tests/test_eval_dataset.py backend/tests/test_eval_runner.py -v  
Expected: FAIL because badcases.json and CLI dataset helpers do not exist.

- [ ] **Step 3: Implement reusable evaluation**

~~~python
parser = argparse.ArgumentParser()
parser.add_argument("--dataset", default="questions.json")
args = parser.parse_args()
items = load_dataset(Path(__file__).parent / args.dataset)
stats, bad = evaluate_items(items)
~~~

Create badcases.json from the nine questions in Step 1. Preserve original expected points except two questions phrased as latest/current logistics nodes: both expect exactly ["运输中"], not complete historical trajectory. Do not change any other question or expected point in this task.

- [ ] **Step 4: Verify dataset behavior without an LLM call**

Run: pytest backend/tests/test_eval_dataset.py backend/tests/test_eval_runner.py -v && python -m eval.judge --help from backend/  
Expected: PASS; help lists --dataset and makes no provider call.

- [ ] **Step 5: Commit**

~~~bash
git add backend/eval/badcases.json backend/eval/judge.py backend/eval/questions.json backend/tests/test_eval_dataset.py backend/tests/test_eval_runner.py
git commit -m "test: add badcase evaluation regression gate"
~~~

### Task 6: Root-cause fixes for nine evaluation bad cases

**Files:**
- Modify: backend/app/agents/nodes.py
- Modify: backend/knowledge_base/policies/7day-no-reason.md
- Modify: backend/knowledge_base/products/electronics.md
- Modify: backend/knowledge_base/misc/account.md
- Modify: backend/tests/test_graph.py
- Create: backend/tests/test_badcase_behavior.py

**Interfaces:**
- router_node sends explicit transfer requests to human, but human-service hours/conditions to policy.
- router_node needs an order ID before the order-tool route; order-related policy/security questions without an ID go to policy.
- build_writer_messages combines successful order results with retrieved policy context for multi-intent questions.

- [ ] **Step 1: Write failing routing/context tests**

~~~python
def test_human_information_questions_stay_in_policy_retrieval():
    assert router_node({"question": "人工客服的服务时间是什么时候？"})["domain"] == "policy"
    assert router_node({"question": "什么情况会转人工客服？"})["domain"] == "policy"
    assert router_node({"question": "请帮我转人工客服"})["domain"] == "human"

def test_order_without_id_is_not_sent_to_order_tool():
    assert router_node({"question": "我的订单里有不认识的商品，怎么申请退款？"})["domain"] == "policy"

def test_order_writer_includes_policy_context_for_damage_question():
    prompt = build_writer_messages({
        "question": "订单20260811001商品破损了，退货运费谁承担？", "domain": "order",
        "history": [], "tool_results": [{"order_id": "20260811001", "status": "已发货"}],
        "retrieved_chunks": [{"title": "质量问题退换货政策", "text": "质量问题退货运费由卖家承担", "score": 0.9}],
    })[-1]["content"]
    assert "已发货" in prompt and "运费由卖家承担" in prompt
~~~

- [ ] **Step 2: Run behavior tests to verify they fail**

Run: pytest backend/tests/test_graph.py backend/tests/test_badcase_behavior.py -v  
Expected: FAIL because the current router over-matches human/order keywords and current order writer discards retrieved policy context.

- [ ] **Step 3: Implement exact root-cause changes**

~~~python
EXPLICIT_HANDOFF_PATTERNS = ("我要转人工", "帮我转人工", "请转人工", "找人工处理", "转真人客服")
ORDER_ID_PATTERN = re.compile(r"订单\s*\d{8,}")

if any(p in q for p in EXPLICIT_HANDOFF_PATTERNS):
    domain = "human"
elif ORDER_ID_PATTERN.search(q):
    domain = "order"
~~~

Keep explicit complaint wording such as 找人工客服投诉 in human. In valid-order writer prompts append reranked context and require both verified order facts and applicable policy. Change OFFTOPIC_REPLY to explicitly refuse unrelated requests and say it will not fabricate information.

Add exact lexical grounding without inventing facts: a heading “已使用的商品申请七天无理由退货” with existing 80% depreciation rule; a heading “Type-C快充数据线长度” with existing 1m/2m options; and a heading “订单中出现不认识的商品” instructing order verification, account protection, and human identity verification.

- [ ] **Step 4: Verify local behavior, reindex, and run only bad cases**

Run: pytest backend/tests/test_graph.py backend/tests/test_badcase_behavior.py -v && python -m app.rag.reindex && python -u -m eval.judge --dataset badcases.json from backend/  
Expected: local tests PASS and regression prints 总准确率: 9/9 = 100%.

If regression is not 9/9, do not run 78 questions. Add a test for the observed root cause, apply the smallest truthful fix in the files above, reindex, and repeat this step until 9/9.

- [ ] **Step 5: Commit only after 9/9**

~~~bash
git add backend/app/agents/nodes.py backend/knowledge_base/policies/7day-no-reason.md backend/knowledge_base/products/electronics.md backend/knowledge_base/misc/account.md backend/tests/test_graph.py backend/tests/test_badcase_behavior.py
git commit -m "fix: close evaluation badcase regressions"
~~~

### Task 7: Full verification, one full evaluation, and truthful documentation

**Files:**
- Modify: README.md only if full evaluation is at least 90%
- Modify: CONTEXT.md only if full evaluation is at least 90%
- Modify: backend/eval_result.txt only if full evaluation is at least 90%

**Interfaces:**
- Consumes a recorded 9/9 badcase result.
- Produces exactly one full-run report and, on success, updated project-facing figures.

- [ ] **Step 1: Verify the badcase gate**

Run: python -u -m eval.judge --dataset badcases.json from backend/  
Expected: exactly 总准确率: 9/9 = 100%. If not, return to Task 6 without running the full suite.

- [ ] **Step 2: Run all local automated tests**

Run: pytest backend/tests -q && npm test && npm run build, using backend/frontend working directories  
Expected: all suites PASS before any paid full run.

- [ ] **Step 3: Reindex and run the full 78-question evaluation exactly once**

Run: python -m app.rag.reindex && python -u -m eval.judge --dataset questions.json | Tee-Object -FilePath eval_result.txt from backend/  
Expected: one real report with category totals, total, and bad cases. Stop the backend server first if it owns Qdrant local index.

- [ ] **Step 4: Apply the result gate**

If the result is at least 71/78 (at least 90% printed), update README and CONTEXT with exact numerator/denominator, date, active primary model, and test totals. Replace the stale encoding-corrupted 25-question output with UTF-8 summary. If below 90%, do not update project-facing claims; append newly failed questions to badcases.json and return to Task 6.

- [ ] **Step 5: Commit success-only verification artifacts**

~~~bash
git add README.md CONTEXT.md backend/eval_result.txt
git commit -m "docs: record 78-question evaluation result"
~~~

Only execute this commit on the successful branch of Step 4. Do not commit .env, Qdrant data, mock database files, or backend/knowledge_base/backfill/.

