import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatWindow from "@/components/ChatWindow";
import { streamChat } from "@/lib/sse";
import { fetchHistory, submitFeedback } from "@/lib/api";

// mock 网络相关模块：ChatWindow 依赖 streamChat（SSE）与 fetchHistory/submitFeedback（REST）。
vi.mock("@/lib/sse", () => ({ streamChat: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchHistory: vi.fn(), submitFeedback: vi.fn() }));

const mockedStreamChat = vi.mocked(streamChat);
const mockedFetchHistory = vi.mocked(fetchHistory);
const mockedSubmitFeedback = vi.mocked(submitFeedback);

// 让 streamChat mock 捕获 handlers，测试再手动触发 onToken/onError/onDone
function captureHandlers() {
  let handlers: any;
  mockedStreamChat.mockImplementation(async (_sid: string, _msg: string, h: any) => {
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

    expect(mockedStreamChat).toHaveBeenCalledWith("s1", "我的订单", expect.any(Object));

    act(() => {
      getHandlers().onToken("您");
      getHandlers().onToken("好");
      getHandlers().onDone();
    });

    expect(screen.getByText("您好")).toBeInTheDocument();
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
    expect(mockedStreamChat).toHaveBeenLastCalledWith("s1", "订单到哪了", expect.any(Object));
  });
});
