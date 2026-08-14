import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatWindow from "@/components/ChatWindow";
import { streamChat } from "@/lib/sse";
import { fetchHistory, submitFeedback, humanReply, backfill, approveBackfill } from "@/lib/api";

// mock 网络相关模块：ChatWindow 依赖 streamChat（SSE）与 fetchHistory/submitFeedback（REST）。
vi.mock("@/lib/sse", () => ({ streamChat: vi.fn(), MAX_HISTORY: 8 }));
vi.mock("@/lib/api", () => ({
  fetchHistory: vi.fn(),
  submitFeedback: vi.fn(),
  humanReply: vi.fn(),
  backfill: vi.fn(),
  approveBackfill: vi.fn(),
}));

const mockedStreamChat = vi.mocked(streamChat);
const mockedFetchHistory = vi.mocked(fetchHistory);
const mockedSubmitFeedback = vi.mocked(submitFeedback);
const mockedHumanReply = vi.mocked(humanReply);
const mockedBackfill = vi.mocked(backfill);
const mockedApproveBackfill = vi.mocked(approveBackfill);

// 让 streamChat mock 捕获 handlers，测试再手动触发 onToken/onError/onDone
function captureHandlers() {
  let handlers: any;
  mockedStreamChat.mockImplementation(async (_sid: string, _msg: string, _hist: any, h: any) => {
    handlers = h;
    return { cancel: vi.fn() };
  });
  return () => handlers;
}

describe("ChatWindow", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedFetchHistory.mockResolvedValue([]);
    mockedSubmitFeedback.mockResolvedValue(true);
  });

  it("初始渲染欢迎语与建议按钮", () => {
    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    expect(screen.getByText(/你好，我是智能客服小商/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "怎么申请退货？" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "订单到哪了？" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退款多久到账？" })).toBeInTheDocument();
  });

  it("输入并发送：调用 streamChat 且流式 token 追加到回答", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();

    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    await user.type(screen.getByPlaceholderText("输入问题…"), "我的订单");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(mockedStreamChat).toHaveBeenCalledWith("s1", "我的订单", expect.any(Array), expect.any(Object));

    act(() => {
      getHandlers().onToken("您");
      getHandlers().onToken("好");
      getHandlers().onDone();
    });

    expect(screen.getByText("您好")).toBeInTheDocument();
  });

  it("第二轮发送时把第一轮对话作为 history 带给后端", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();

    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    // 第一轮
    await user.type(screen.getByPlaceholderText("输入问题…"), "订单到哪了");
    await user.click(screen.getByRole("button", { name: "发送" }));
    act(() => {
      getHandlers().onToken("已发货");
      getHandlers().onDone();
    });
    // 第二轮
    await user.type(screen.getByPlaceholderText("输入问题…"), "那物流呢");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const secondCall = mockedStreamChat.mock.calls[1];
    expect(secondCall[1]).toBe("那物流呢");
    // history 包含第一轮的 user + assistant 两条消息
    expect(secondCall[2]).toEqual([
      { role: "user", content: "订单到哪了" },
      { role: "assistant", content: "已发货" },
    ]);
  });

  it("新消息到达时自动滚动到底部", async () => {
    const user = userEvent.setup();
    captureHandlers();

    const { container } = render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    const scroller = container.querySelector(".overflow-y-auto") as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, get: () => 800 });
    Object.defineProperty(scroller, "scrollTop", { configurable: true, writable: true, value: 0 });

    await user.type(screen.getByPlaceholderText("输入问题…"), "hi");
    await user.click(screen.getByRole("button", { name: "发送" }));

    // messages 变化触发 scroll effect：scrollTop 被置为 scrollHeight(800)
    expect(scroller.scrollTop).toBe(800);
  });

  it("onError 后回答标记失败并出现「🔄 重试」按钮", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();

    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    await user.type(screen.getByPlaceholderText("输入问题…"), "订单到哪了");
    await user.click(screen.getByRole("button", { name: "发送" }));

    act(() => {
      getHandlers().onError("服务暂时不可用，请稍后重试");
      getHandlers().onDone();
    });

    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    expect(screen.getByText(/服务暂时不可用/)).toBeInTheDocument();
  });

  it("点击重试会重新发起 streamChat", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();

    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    await user.type(screen.getByPlaceholderText("输入问题…"), "订单到哪了");
    await user.click(screen.getByRole("button", { name: "发送" }));

    // 触发 onError：回答标记失败、setBusy(false)，出现「🔄 重试」按钮
    act(() => {
      getHandlers().onError("服务暂时不可用，请稍后重试");
      getHandlers().onDone();
    });

    const retryBtn = screen.getByRole("button", { name: /重试/ });
    expect(retryBtn).toBeInTheDocument();

    await user.click(retryBtn);

    // retry() 移除失败的 user+assistant 轮次并重新 send(retryText) → 再次调 streamChat
    expect(mockedStreamChat).toHaveBeenCalledTimes(2);
    // 第二次调用的 user 消息文本与原来一致
    expect(mockedStreamChat.mock.calls[1][1]).toBe("订单到哪了");
    expect(mockedStreamChat).toHaveBeenLastCalledWith("s1", "订单到哪了", expect.any(Array), expect.any(Object));
  });

  it("收到 human_handoff 后显示转人工按钮", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();
    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    await user.type(screen.getByPlaceholderText("输入问题…"), "怎么开电子发票");
    await user.click(screen.getByRole("button", { name: "发送" }));
    act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
    expect(await screen.findByRole("button", { name: /转人工/ })).toBeInTheDocument();
  });

  it("转人工 → 回复 → 沉淀 → 发布 完整流程", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();
    mockedHumanReply.mockResolvedValue(true);
    mockedBackfill.mockResolvedValue({
      status: "draft", doc_id: "x.md", path: "backfill/x.md", title: "开票指南",
    });
    mockedApproveBackfill.mockResolvedValue(true);
    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    await user.type(screen.getByPlaceholderText("输入问题…"), "怎么开电子发票");
    await user.click(screen.getByRole("button", { name: "发送" }));
    act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
    await user.click(await screen.findByRole("button", { name: /转人工/ }));
    await user.type(screen.getByPlaceholderText("输入人工客服的回答…"), "请联系财务开具");
    await user.click(screen.getByRole("button", { name: "回复" }));
    expect(mockedHumanReply).toHaveBeenCalledWith("s1", "怎么开电子发票", "请联系财务开具");
    expect(await screen.findByText(/（人工客服）请联系财务开具/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "沉淀" }));
    expect(mockedBackfill).toHaveBeenCalledWith("怎么开电子发票", "请联系财务开具");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    expect(mockedApproveBackfill).toHaveBeenCalledWith("x.md");
    expect(screen.getByText(/已发布/)).toBeInTheDocument();
  });

  it("第二次 human_handoff 后弹窗复位到回复步骤", async () => {
    const user = userEvent.setup();
    const getHandlers = captureHandlers();
    mockedHumanReply.mockResolvedValue(true);
    mockedBackfill.mockResolvedValue({ status: "draft", doc_id: "x.md", path: "backfill/x.md", title: "t" });
    mockedApproveBackfill.mockResolvedValue(true);
    render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
    // 第一轮完整流程
    await user.type(screen.getByPlaceholderText("输入问题…"), "问题A");
    await user.click(screen.getByRole("button", { name: "发送" }));
    act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
    await user.click(await screen.findByRole("button", { name: /转人工/ }));
    await user.type(screen.getByPlaceholderText("输入人工客服的回答…"), "答案A");
    await user.click(screen.getByRole("button", { name: "回复" }));
    await user.click(screen.getByRole("button", { name: "沉淀" }));
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    // 第二轮 handoff：弹窗应回到 reply（出现文本域），而非显示「已发布」
    await user.type(screen.getByPlaceholderText("输入问题…"), "问题B");
    await user.click(screen.getByRole("button", { name: "发送" }));
    act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
    // 两轮 assistant 消息都带 handoff 标记，会有多个「转人工」按钮，点击最后一轮的那个
    const handoffButtons = await screen.findAllByRole("button", { name: /转人工/ });
    await user.click(handoffButtons[handoffButtons.length - 1]);
    expect(screen.getByPlaceholderText("输入人工客服的回答…")).toBeInTheDocument();
    expect(screen.queryByText(/已发布/)).not.toBeInTheDocument();
  });
});
