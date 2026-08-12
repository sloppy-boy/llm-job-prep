import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MessageCard from "@/components/MessageCard";

describe("MessageCard", () => {
  it("渲染 order 卡片字段", () => {
    render(
      <MessageCard
        card={{ kind: "order", data: { order_id: "O123", status: "已发货", items: "手机x1", amount: 3999 } }}
      />
    );
    expect(screen.getByText(/O123/)).toBeInTheDocument();
    expect(screen.getByText(/已发货/)).toBeInTheDocument();
    expect(screen.getByText(/手机x1/)).toBeInTheDocument();
    expect(screen.getByText(/¥3999/)).toBeInTheDocument();
  });

  it("渲染 logistics 轨迹数组的每条 time/event", () => {
    render(
      <MessageCard
        card={{
          kind: "logistics",
          data: [
            { time: "2024-01-01 10:00", event: "已揽收" },
            { time: "2024-01-02 12:00", event: "运输中" },
          ],
        }}
      />
    );
    expect(screen.getByText("2024-01-01 10:00")).toBeInTheDocument();
    expect(screen.getByText("已揽收")).toBeInTheDocument();
    expect(screen.getByText("2024-01-02 12:00")).toBeInTheDocument();
    expect(screen.getByText("运输中")).toBeInTheDocument();
  });

  it("logistics 空数组显示「暂无物流轨迹」", () => {
    render(<MessageCard card={{ kind: "logistics", data: [] }} />);
    expect(screen.getByText("暂无物流轨迹")).toBeInTheDocument();
  });

  it("渲染 refund 卡片字段", () => {
    render(<MessageCard card={{ kind: "refund", data: { refund_id: "R001", status: "审核中" } }} />);
    expect(screen.getByText(/R001/)).toBeInTheDocument();
    expect(screen.getByText(/审核中/)).toBeInTheDocument();
  });

  it("未知 kind 返回 null 不崩溃", () => {
    const { container } = render(<MessageCard card={{ kind: "bogus", data: { a: 1 } }} />);
    expect(container.firstChild).toBeNull();
  });

  it("kind 为 logistics 但 data 不是数组时安全返回 null", () => {
    const { container } = render(<MessageCard card={{ kind: "logistics", data: { time: "x" } }} />);
    expect(container.firstChild).toBeNull();
  });

  it("kind 为 order 但 data 缺失字段时安全渲染占位符", () => {
    render(<MessageCard card={{ kind: "order", data: {} }} />);
    expect(screen.getAllByText(/—/).length).toBeGreaterThan(0);
  });
});
