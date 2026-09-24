import { describe, expect, it } from "vitest";

import { getErrorMessage } from "../lib/errorMessages";

describe("getErrorMessage", () => {
  it("maps validation errors to Chinese copy", () => {
    expect(getErrorMessage({ status: 422, detail: "Validation error" })).toBe("请求参数不完整或格式不正确，请检查后重试");
  });

  it("keeps Chinese backend messages", () => {
    expect(getErrorMessage({ status: 400, detail: "代理绑定已存在" })).toBe("代理绑定已存在");
  });

  it("falls back to a generic network error message", () => {
    expect(getErrorMessage({ message: "Failed to fetch" })).toBe("网络连接异常，请检查网络后重试");
  });
});
