interface ErrorShape {
  status?: number;
  detail?: string;
  message?: string;
}

const GENERIC_MESSAGES: Record<number, string> = {
  400: "请求未通过，请检查输入后重试",
  401: "登录已失效，请重新登录",
  403: "当前账号没有权限执行这个操作",
  404: "请求的内容不存在或已被删除",
  409: "当前操作与已有数据冲突，请刷新后重试",
  422: "请求参数不完整或格式不正确，请检查后重试",
  500: "服务器处理请求时出现问题，请稍后重试",
  502: "服务暂时不可用，请稍后重试",
  503: "服务暂时不可用，请稍后重试",
  504: "服务响应超时，请稍后重试",
};

function isChineseText(value: string): boolean {
  return /[\u4e00-\u9fff]/.test(value);
}

export function getErrorMessage(error: ErrorShape): string {
  const detail = error.detail?.trim();
  const message = error.message?.trim();

  if (detail && isChineseText(detail)) {
    return detail;
  }

  if (message && isChineseText(message)) {
    return message;
  }

  if (detail === "Validation error" || message === "Validation error" || error.status === 422) {
    return GENERIC_MESSAGES[422];
  }

  if (message && /failed to fetch|network|load failed/i.test(message)) {
    return "网络连接异常，请检查网络后重试";
  }

  if (error.status && GENERIC_MESSAGES[error.status]) {
    return GENERIC_MESSAGES[error.status];
  }

  return "操作失败，请稍后重试";
}

