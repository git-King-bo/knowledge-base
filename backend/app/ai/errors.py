"""Safe, actionable model errors; never forward credential-bearing response bodies."""
import httpx
from fastapi import HTTPException


def model_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return {
            400: '模型服务拒绝请求（400），请检查模型名称、思考模式及参数是否受支持。',
            401: '模型服务认证失败（401），请检查 API Key。',
            403: '模型服务拒绝访问（403），请确认账号已开通该模型。',
            404: '模型或接口不存在（404），请检查模型名称的大小写、API 地址及模型访问权限。',
            429: '模型服务限流或额度不足（429），请检查服务商额度并稍后重试。',
        }.get(status, f'模型服务返回错误（{status}），请稍后重试。')
    if isinstance(exc, httpx.TimeoutException):
        return '等待模型响应超时，请稍后重试，或关闭思考模式后再试。'
    if isinstance(exc, httpx.RequestError):
        return '模型服务连接中断，请检查网络后重试。'
    if isinstance(exc, HTTPException) and exc.status_code == 429:
        return '系统调用预算或并发已达上限，请稍后重试或检查系统额度。'
    return '回答生成中断，请重试。'
