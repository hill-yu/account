import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastContext } from "../components/ui/useToast";
import { TasksSection } from "../features/tasks/TasksSection";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("TasksSection pagination", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function renderTasks(total: number, page = 1, loading = false) {
    const onPreviousPage = vi.fn();
    const onNextPage = vi.fn();
    await act(async () => {
      root.render(
        <ToastContext.Provider value={{ pushToast: vi.fn() }}>
          <TasksSection
            accounts={[]}
            instances={[]}
            tasks={[]}
            onChanged={vi.fn()}
            page={page}
            pageSize={100}
            total={total}
            loading={loading}
            onPreviousPage={onPreviousPage}
            onNextPage={onNextPage}
          />
        </ToastContext.Provider>,
      );
    });
    return { onPreviousPage, onNextPage };
  }

  function button(label: string): HTMLButtonElement {
    const match = [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === label);
    if (!(match instanceof HTMLButtonElement)) throw new Error(`Button not found: ${label}`);
    return match;
  }

  it("shows page count and advances without invoking the previous-page callback", async () => {
    const { onPreviousPage, onNextPage } = await renderTasks(205);

    expect(container.textContent).toContain("第 1 / 3 页");
    expect(container.textContent).toContain("共 205 条");
    expect(button("上一页").disabled).toBe(true);
    expect(button("下一页").disabled).toBe(false);

    await act(async () => button("下一页").click());
    expect(onNextPage).toHaveBeenCalledTimes(1);
    expect(onPreviousPage).not.toHaveBeenCalled();
  });

  it("renders an empty snapshot as page one of one with both controls disabled", async () => {
    await renderTasks(0);

    expect(container.textContent).toContain("第 1 / 1 页");
    expect(container.textContent).toContain("共 0 条");
    expect(button("上一页").disabled).toBe(true);
    expect(button("下一页").disabled).toBe(true);
  });

  it("enables Previous on the last page, invokes it, and disables Next", async () => {
    const { onPreviousPage, onNextPage } = await renderTasks(205, 3);

    expect(container.textContent).toContain("第 3 / 3 页");
    expect(button("上一页").disabled).toBe(false);
    expect(button("下一页").disabled).toBe(true);
    await act(async () => button("上一页").click());
    expect(onPreviousPage).toHaveBeenCalledTimes(1);
    expect(onNextPage).not.toHaveBeenCalled();
  });

  it("disables both pagination controls while a page is loading", async () => {
    await renderTasks(205, 2, true);

    expect(button("上一页").disabled).toBe(true);
    expect(button("下一页").disabled).toBe(true);
  });
});
