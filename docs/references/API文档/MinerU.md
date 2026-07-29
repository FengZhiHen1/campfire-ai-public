# MinerU API 文档

MinerU 提供两种文档提取 API，满足不同场景需求：

- 🎯 **Precision Extract API** — 需要 Token；支持单文件/批量文件、表格/公式识别、多格式输出
- ⚡ **Agent Lightweight Extract API** — 无需登录；IP 限流防止滥用；专为 AI Agent 工作流设计

---

## 模式对比

| 特性 | Precision Extract API | Agent Lightweight Extract API |
|------|----------------------|------------------------------|
| Token 要求 | 需要 | 不需要 |
| 限流方式 | 每日页数配额 | IP 分钟级限流 |
| 支持模型 | pipeline / vlm / MinerU-HTML | pipeline 轻量版 |
| 输出格式 | ZIP（结构化数据 + 多格式） | Markdown  only |
| 适用场景 | 高精度、复杂文档深度提取 | AI Agent 快速集成 |

---

# 一、Precision Extract API

> 需要 Token。支持 pipeline / vlm / MinerU-HTML 模型，支持单文件和批量处理。

## 1.1 概述

Precision Extract API 专为需要高精度、深度结构化提取的复杂文档设计。可智能识别并处理各类复杂版式与多模态内容（如表格、数学公式、图表、图片、多栏布局等），将文档内容转换为高质量结构化数据。

**核心特性：**

- **极致精度**：业界领先的提取精度，尤其擅长非标准和复杂文档
- **深度结构化**：超越简单文本提取，深度理解文档版式与语义，输出具有丰富层级关系的结构化数据
- **多模态支持**：全面支持文本、表格、图片、公式等内容类型的精准识别与提取
- **复杂版式适配**：有效处理扫描文档、乱排版、水印干扰等复杂文档场景

**文件限制：**

- 单个文件最大 200MB，最多 200 页
- 每个账户每日配额 1,000 页（最高优先级），超出后降低优先级
- GitHub、AWS 等海外服务 URL 可能因网络限制超时
- 不支持直接文件上传（需通过 URL 或预签名上传）

---

## 1.2 创建提取任务（URL 方式）

**Endpoint：** `POST https://mineru.net/api/v4/extract/task`

**说明：** 通过 API 创建提取任务。需先申请 Token。

**注意事项：**

- 最大文件大小 200MB，最大页数 200 页
- 每日配额 1,000 页（最高优先级），超出后降低优先级
- GitHub、AWS 等海外服务 URL 可能超时
- 不支持直接文件上传
- Header 必须包含 `Authorization` 字段，格式：`Bearer {token}`

**请求体参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | 文件 URL |
| `model_version` | string | 是 | 模型版本：`vlm`、`pipeline` 或 `MinerU-HTML` |

**Python 示例（PDF、Doc、PPT、Excel、图片文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/extract/task"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "model_version": "vlm"
}

res = requests.post(url, headers=header, json=data)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

**Python 示例（HTML 文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/extract/task"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "url": "https://****",
    "model_version": "MinerU-HTML"
}

res = requests.post(url, headers=header, json=data)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

**CURL 示例（PDF、Doc、PPT、Excel、图片文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "model_version": "vlm"
}'
```

**CURL 示例（HTML 文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "url": "https://****",
    "model_version": "MinerU-HTML"
}'
```

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b4***"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 1.3 查询任务结果

**Endpoint：** `GET https://mineru.net/api/v4/extract/task/{task_id}`

**说明：** 通过 `task_id` 查询提取任务当前进度。任务完成后返回提取详情。

**Python 示例：**

```python
import requests

token = "your api token from the website"
task_id = "task_id returned from the previous step"
url = f"https://mineru.net/api/v4/extract/task/{task_id}"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

res = requests.get(url, headers=header)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

**CURL 示例：**

```bash
curl --location --request GET 'https://mineru.net/api/v4/extract/task/{task_id}' \
--header 'Authorization: Bearer *****' \
--header 'Accept: */*'
```

**响应示例（进行中）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "47726b6e-46ca-4bb9-******",
    "state": "running",
    "err_msg": "",
    "extract_progress": {
      "extracted_pages": 1,
      "total_pages": 2,
      "start_time": "2025-01-20 11:43:20"
    }
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

**响应示例（已完成）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "47726b6e-46ca-4bb9-******",
    "state": "done",
    "full_zip_url": "https://cdn-mineru.openxlab.org.cn/pdf/018e53ad-d4f1-475d-b380-36bf24db9914.zip",
    "err_msg": ""
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 1.4 批量获取文件上传 URL（预签名上传）

**Endpoint：** `POST https://mineru.net/api/v4/file-urls/batch`

**说明：** 用于上传本地文件进行提取。可通过此接口批量申请文件上传 URL，上传后系统自动提交提取任务。

**注意事项：**

- 文件上传 URL 有效期 24 小时，请在此期间完成上传
- 上传文件时不需要 Content-Type Header
- 文件上传完成后无需调用提交任务接口，系统将自动扫描上传文件并提交提取任务
- 每次请求最多 50 个 URL
- Header 必须包含 `Authorization` 字段，格式：`Bearer {token}`

**请求体参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | array | 是 | 文件列表，每项为 `{"name": "文件名", "data_id": "业务ID"}` |
| `model_version` | string | 是 | 模型版本：`vlm`、`pipeline` 或 `MinerU-HTML` |

**Python 示例（PDF、Doc、PPT、Excel、图片文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/file-urls/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"name":"demo.pdf", "data_id": "abcd"}
    ],
    "model_version":"vlm"
}
file_path = ["demo.pdf"]
try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        print('response success. result:{}'.format(result))
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            urls = result["data"]["file_urls"]
            print('batch_id:{},urls:{}'.format(batch_id, urls))
            for i in range(0, len(urls)):
                with open(file_path[i], 'rb') as f:
                    res_upload = requests.put(urls[i], data=f)
                    if res_upload.status_code == 200:
                        print(f"{urls[i]} upload success")
                    else:
                        print(f"{urls[i]} upload failed")
        else:
            print('apply upload url failed,reason:{}'.format(result["msg"]))
    else:
        print('response not success. status:{} ,result:{}'.format(response.status_code, response))
except Exception as err:
    print(err)
```

**Python 示例（HTML 文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/file-urls/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"name":"demo.html", "data_id": "abcd"}
    ],
    "model_version":"MinerU-HTML"
}
file_path = ["demo.html"]
try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        print('response success. result:{}'.format(result))
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            urls = result["data"]["file_urls"]
            print('batch_id:{},urls:{}'.format(batch_id, urls))
            for i in range(0, len(urls)):
                with open(file_path[i], 'rb') as f:
                    res_upload = requests.put(urls[i], data=f)
                    if res_upload.status_code == 200:
                        print(f"{urls[i]} upload success")
                    else:
                        print(f"{urls[i]} upload failed")
        else:
            print('apply upload url failed,reason:{}'.format(result["msg"]))
    else:
        print('response not success. status:{} ,result:{}'.format(response.status_code, response))
except Exception as err:
    print(err)
```

**CURL 示例（PDF、Doc、PPT、Excel、图片文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/file-urls/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"name":"demo.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}'
```

**CURL 示例（HTML 文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/file-urls/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"name":"demo.html", "data_id": "abcd"}
    ],
    "model_version": "MinerU-HTML"
}'
```

**CURL 文件上传示例：**

```bash
curl -X PUT -T /path/to/your/file.pdf 'https://****'
```

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
    "file_urls": ["https://***"]
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 1.5 批量创建提取任务

**Endpoint：** `POST https://mineru.net/api/v4/extract/task/batch`

**说明：** 通过 API 批量创建提取任务。

**注意事项：**

- 每次请求最多 50 个 URL
- 最大文件大小 200MB，最大页数 200 页
- GitHub、AWS 等海外服务 URL 可能超时
- Header 必须包含 `Authorization` 字段，格式：`Bearer {token}`

**请求体参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | array | 是 | 文件列表，每项为 `{"url": "文件URL", "data_id": "业务ID"}` |
| `model_version` | string | 是 | 模型版本 |

**请求体示例：**

```json
{
  "files": [
    {
      "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
      "data_id": "abcd"
    }
  ],
  "model_version": "vlm"
}
```

**Python 示例（PDF、Doc、PPT、Excel、图片文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/extract/task/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"url":"https://cdn-mineru.openxlab.org.cn/demo/example.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}
try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        print('response success. result:{}'.format(result))
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            print('batch_id:{}'.format(batch_id))
        else:
            print('submit task failed,reason:{}'.format(result["msg"]))
    else:
        print('response not success. status:{} ,result:{}'.format(response.status_code, response))
except Exception as err:
    print(err)
```

**Python 示例（HTML 文件）：**

```python
import requests

token = "your api token from the website"
url = "https://mineru.net/api/v4/extract/task/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"url":"https://***", "data_id": "abcd"}
    ],
    "model_version": "MinerU-HTML"
}
try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        print('response success. result:{}'.format(result))
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            print('batch_id:{}'.format(batch_id))
        else:
            print('submit task failed,reason:{}'.format(result["msg"]))
    else:
        print('response not success. status:{} ,result:{}'.format(response.status_code, response))
except Exception as err:
    print(err)
```

**CURL 示例（PDF、Doc、PPT、Excel、图片文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"url":"https://cdn-mineru.openxlab.org.cn/demo/example.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}'
```

**CURL 示例（HTML 文件）：**

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"url":"https://***", "data_id": "abcd"}
    ],
    "model_version": "MinerU-HTML"
}'
```

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 1.6 批量查询任务结果

**Endpoint：** `GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`

**说明：** 通过 `batch_id` 查询批量提取任务进度。

**Python 示例：**

```python
import requests

token = "your api token from the website"
batch_id = "batch_id returned from the previous step"
url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

res = requests.get(url, headers=header)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

**CURL 示例：**

```bash
curl --location --request GET 'https://mineru.net/api/v4/extract-results/batch/{batch_id}' \
--header 'Authorization: Bearer *****' \
--header 'Accept: */*'
```

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
    "extract_result": [
      {
        "file_name": "example.pdf",
        "state": "done",
        "err_msg": "",
        "full_zip_url": "https://cdn-mineru.openxlab.org.cn/pdf/018e53ad-d4f1-475d-b380-36bf24db9914.zip"
      },
      {
        "file_name": "demo.pdf",
        "state": "running",
        "err_msg": "",
        "extract_progress": {
          "extracted_pages": 1,
          "total_pages": 2,
          "start_time": "2025-01-20 11:43:20"
        }
      }
    ]
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 1.7 常用错误码

| 错误码    | 说明                | 解决建议                                                                                    |
| ------ | ----------------- | --------------------------------------------------------------------------------------- |
| A0202  | Token 错误          | 检查 Token 是否正确，请检查是否有 Bearer 前缀或者更换新 Token                                               |
| A0211  | Token 过期          | 更换新 Token                                                                               |
| -500   | 传参错误              | 请确保参数类型及 Content-Type 正确                                                                |
| -10001 | 服务异常              | 请稍后再试                                                                                   |
| -10002 | 请求参数错误            | 检查请求参数格式                                                                                |
| -60001 | 生成上传 URL 失败，请稍后再试 | 请稍后再试                                                                                   |
| -60002 | 获取匹配的文件格式失败       | 检测文件类型失败，请求的文件名及链接中带有正确的后缀名，且文件为 pdf, doc, docx, ppt, pptx, xls, xlsx, png, jp(e)g 中的一种 |
| -60003 | 文件读取失败            | 请检查文件是否损坏并重新上传                                                                          |
| -60004 | 空文件               | 请上传有效文件                                                                                 |
| -60005 | 文件大小超出限制          | 检查文件大小，最大支持 200MB                                                                       |
| -60006 | 文件页数超过限制          | 请拆分文件后重试                                                                                |
| -60007 | 模型服务暂时不可用         | 请稍后重试或联系技术支持                                                                            |
| -60008 | 文件读取超时            | 检查 URL 可访问                                                                              |
| -60009 | 任务提交队列已满          | 请稍后再试                                                                                   |
| -60010 | 解析失败              | 请稍后再试                                                                                   |
| -60011 | 获取有效文件失败          | 请确保文件已上传                                                                                |
| -60012 | 找不到任务             | 请确保 task\_id 有效且未删除                                                                     |
| -60013 | 没有权限访问该任务         | 只能访问自己提交的任务                                                                             |
| -60014 | 删除运行中的任务          | 运行中的任务暂不支持删除                                                                            |
| -60015 | 文件转换失败            | 可以手动转为 pdf 再上传                                                                          |
| -60016 | 文件转换失败            | 文件转换为指定格式失败，可以尝试其他格式导出或重试                                                               |
| -60017 | 重试次数达到上限          | 等后续模型升级后重试                                                                              |
| -60018 | 每日解析任务数量已达上限      | 明日再来                                                                                    |
| -60019 | html 文件解析额度不足     | 明日再来                                                                                    |
| -60020 | 文件拆分失败            | 请稍后重试                                                                                   |
| -60021 | 读取文件页数失败          | 请稍后重试                                                                                   |
| -60022 | 网页读取失败            | 可能因网络问题或者限频导致读取失败，请稍后重试                                                                 |

---

# 二、Agent Lightweight Extract API

> 无需登录，不需要 Token。IP 限流防止滥用。专为 OpenClaw 等 AI Agent 场景设计，仅输出 Markdown，零门槛接入。

## 2.1 概述

Agent Lightweight Extract API 专为 OpenClaw 等 AI Agent 场景设计，提供快速、免登录的文档提取能力。

**核心特性：**

- **无需登录**：IP 限流防止滥用，不需要 Token
- **轻量快速**：PDF 和图片使用 pipeline 轻量模型，关闭表格/公式识别以获得最大提取速度；Word 和 PPT 使用原生 Office API 解析
- **统一输出**：仅输出 Markdown 格式，返回 CDN 链接
- **双提交模式**：URL 提取和文件上传分为独立端点；文件上传使用预签名 URL 模式

**文件限制：**

- PDF / 图片：最多 50 页
- Word / PPT：最多 100 页
- 单个文件最大 50MB

**IP 限流：**

- 每个 IP 有每分钟请求提交限制
- 超出限制将返回 HTTP 429 状态码

---

## 2.2 URL 解析端点

**Endpoint：** `POST https://mineru.net/api/v1/agent/parse/url`

**说明：** 提交远程文件 URL 进行提取。后端自动下载并解析文件。

该端点为异步操作——提交成功后返回 `task_id`，需轮询查询端点获取结果。

**请求体参数（JSON）：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `url` | string | 是 | - | 文件 URL |
| `language` | string | 否 | `"ch"` | 语言代码 |
| `page_range` | string | 否 | - | 页码范围，如 `"1-10"` |
| `enable_table` | boolean | 否 | `true` | 启用表格识别 |
| `is_ocr` | boolean | 否 | `false` | 强制 OCR |
| `enable_formula` | boolean | 否 | `true` | 启用公式识别 |

**注意事项：**

- 不需要 Authorization Header
- 请求体为 JSON 格式（`Content-Type: application/json`），不支持 `multipart/form-data`

**Python 示例：**

```python
import requests

url = "https://mineru.net/api/v1/agent/parse/url"

data = {
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "language": "ch",
    "page_range": "1-10",
    "enable_table": True,
    "is_ocr": False,
    "enable_formula": True
}

res = requests.post(url, json=data)
print(res.json())
```

**CURL 示例：**

```bash
curl --location --request POST 'https://mineru.net/api/v1/agent/parse/url' \
--header 'Content-Type: application/json' \
--data-raw '{
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "language": "ch",
    "page_range": "1-10",
    "enable_table": true,
    "is_ocr": false,
    "enable_formula": true
}'
```

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 2.3 本地文件上传端点（预签名上传）

**Endpoint：** `POST https://mineru.net/api/v1/agent/parse/file`

**说明：** 提交文件上传提取任务。该端点使用**预签名上传模式**：

1. 调用此接口传入文件名等参数，获取 `task_id` 和 OSS 预签名上传 URL（`file_url`）
2. 客户端使用 `PUT` 方法直接将文件上传至 `file_url`
3. 上传完成后，后端自动检测并开始提取
4. 轮询查询端点获取提取结果

**请求体参数（JSON）：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file_name` | string | 是 | - | 文件名（需包含扩展名） |
| `language` | string | 否 | `"ch"` | 语言代码 |
| `page_range` | string | 否 | - | 页码范围 |
| `enable_table` | boolean | 否 | `true` | 启用表格识别 |
| `is_ocr` | boolean | 否 | `false` | 强制 OCR |
| `enable_formula` | boolean | 否 | `true` | 启用公式识别 |

**注意事项：**

- 不需要 Authorization Header
- 请求体为 JSON 格式（`application/json`）
- 不支持批量上传，每次请求只能上传一个文件

**响应示例：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605",
    "file_url": "https://oss-mineru.openxlab.org.cn/agent/a90e6ab6-...pdf?Expires=..."
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

**Python 示例（完整预签名上传流程）：**

```python
import requests

# Step 1: 获取预签名上传 URL
api_url = "https://mineru.net/api/v1/agent/parse/file"
data = {
    "file_name": "document.pdf",
    "language": "ch",
    "page_range": "1-10",
    "enable_table": True,
    "is_ocr": False,
    "enable_formula": True
}

res = requests.post(api_url, json=data)
result = res.json()
task_id = result["data"]["task_id"]
file_url = result["data"]["file_url"]

print(f"Task created, task_id: {task_id}")

# Step 2: PUT 上传文件到 OSS
with open("document.pdf", "rb") as f:
    put_res = requests.put(file_url, data=f)
    print(f"File upload status: {put_res.status_code}")
```

**CURL 示例：**

```bash
# Step 1: 获取预签名上传 URL
curl --location --request POST 'https://mineru.net/api/v1/agent/parse/file' \
--header 'Content-Type: application/json' \
--data-raw '{
    "file_name": "document.pdf",
    "language": "ch",
    "page_range": "1-10",
    "enable_table": true,
    "is_ocr": false,
    "enable_formula": true
}'

# Step 2: PUT 上传文件到返回的 file_url
curl --location --request PUT '<file_url>' \
--data-binary '@document.pdf'
```

---

## 2.4 查询任务结果

**Endpoint：** `GET https://mineru.net/api/v1/agent/parse/{task_id}`

**Python 示例：**

```python
import requests

task_id = "a90e6ab6-44f3-4554-b459-b62fe4c6b43605"
url = f"https://mineru.net/api/v1/agent/parse/{task_id}"

res = requests.get(url)
print(res.json())
```

**CURL 示例：**

```bash
curl --location --request GET 'https://mineru.net/api/v1/agent/parse/{task_id}'
```

**响应示例（等待文件上传——仅文件上传模式）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605",
    "state": "waiting-file"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

**响应示例（处理中）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605",
    "state": "running"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

**响应示例（已完成）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605",
    "state": "done",
    "markdown_url": "https://cdn-mineru.openxlab.org.cn/pdf/a90e6ab6-.../full.md"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

**响应示例（失败）：**

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b459-b62fe4c6b43605",
    "state": "failed",
    "err_code": -30003,
    "err_msg": "file page count exceeds lightweight API limit (50 pages), please use the standard API"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 2.5 完整使用示例（Python）

**URL 模式：**

```python
import requests
import time

BASE_URL = "https://mineru.net/api/v1/agent"

def parse_by_url(url, language="ch", page_range=None, enable_table=True, is_ocr=False, enable_formula=True):
    """通过 URL 提交文档提取任务并等待结果。"""
    # 1. 提交 URL 提取任务
    data = {"url": url, "language": language, "enable_table": enable_table, "is_ocr": is_ocr, "enable_formula": enable_formula}
    if page_range:
        data["page_range"] = page_range

    resp = requests.post(f"{BASE_URL}/parse/url", json=data)
    result = resp.json()
    if result["code"] != 0:
        print(f"Submission failed: {result['msg']}")
        return None

    task_id = result["data"]["task_id"]
    print(f"Task submitted, task_id: {task_id}")

    # 2. 轮询结果
    return poll_result(task_id)

def poll_result(task_id, timeout=300, interval=3):
    """轮询提取结果。"""
    state_labels = {
        "uploading": "Downloading file",
        "pending": "Queued",
        "running": "Extracting",
        "waiting-file": "Waiting for file upload",
    }
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE_URL}/parse/{task_id}")
        result = resp.json()
        state = result["data"]["state"]
        elapsed = int(time.time() - start)

        if state == "done":
            markdown_url = result["data"]["markdown_url"]
            print(f"[{elapsed}s] Extracting complete, Markdown download link: {markdown_url}")
            md_resp = requests.get(markdown_url)
            return md_resp.text

        if state == "failed":
            print(f"[{elapsed}s] extract failed: {result['data'].get('err_msg', 'Unknown error')}")
            return None

        print(f"[{elapsed}s] {state_labels.get(state, state)}...")
        time.sleep(interval)

    print(f"Polling timed out ({timeout}s), please manually query task_id: {task_id}")
    return None

# 使用示例
content = parse_by_url("https://cdn-mineru.openxlab.org.cn/demo/example.pdf")
```

**文件上传模式（预签名上传）：**

```python
import requests
import time

BASE_URL = "https://mineru.net/api/v1/agent"

def parse_by_file(file_path, language="ch", page_range=None, enable_table=True, is_ocr=False, enable_formula=True):
    """通过文件上传提交文档提取任务并等待结果。"""
    file_name = file_path.split("/")[-1].split("\\")[-1]

    # 1. 获取预签名上传 URL
    data = {"file_name": file_name, "language": language, "enable_table": enable_table, "is_ocr": is_ocr, "enable_formula": enable_formula}
    if page_range:
        data["page_range"] = page_range

    resp = requests.post(f"{BASE_URL}/parse/file", json=data)
    result = resp.json()
    if result["code"] != 0:
        print(f"Failed to get upload URL: {result['msg']}")
        return None

    task_id = result["data"]["task_id"]
    file_url = result["data"]["file_url"]
    print(f"Task created, task_id: {task_id}")

    # 2. PUT 上传文件到 OSS
    with open(file_path, "rb") as f:
        put_resp = requests.put(file_url, data=f)
        if put_resp.status_code not in (200, 201):
            print(f"File upload failed, HTTP {put_resp.status_code}")
            return None
    print("File uploaded successfully, waiting for extract...")

    # 3. 轮询结果
    return poll_result(task_id)

def poll_result(task_id, timeout=300, interval=3):
    """轮询提取结果。"""
    state_labels = {
        "pending": "Queued",
        "running": "Extracting",
        "waiting-file": "Waiting for file upload",
    }
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE_URL}/parse/{task_id}")
        result = resp.json()
        state = result["data"]["state"]
        elapsed = int(time.time() - start)

        if state == "done":
            markdown_url = result["data"]["markdown_url"]
            print(f"[{elapsed}s] extract complete, Markdown download link: {markdown_url}")
            md_resp = requests.get(markdown_url)
            return md_resp.text

        if state == "failed":
            print(f"[{elapsed}s] extract failed: {result['data'].get('err_msg', 'Unknown error')}")
            return None

        print(f"[{elapsed}s] {state_labels.get(state, state)}...")
        time.sleep(interval)

    print(f"Polling timed out ({timeout}s), please manually query task_id: {task_id}")
    return None

# 使用示例
content = parse_by_file("./document.pdf")
```

---

## 2.6 Agent 专属错误码

| 错误码    | 说明                 | Agent 应对策略                |
| ------ | ------------------ | ------------------------- |
| -30001 | 文件大小超出轻量接口限制（10MB） | 请使用标准 API 或拆分文件           |
| -30002 | 轻量接口不支持该文件类型       | 请上传 PDF/图片/Doc/PPT/Excel  |
| -30003 | 文件页数超出轻量接口限制       | 请使用标准 API 或指定 page\_range |
| -30004 | 请求参数错误             | 检查必填参数是否缺失                |


---

## 2.7 语言代码参考

使用 `language` 字段，默认值为 `ch`。

**独立语言包：**

| 语言 | 代码 |
|------|------|
| 简体中文 | `ch` |
| 繁体中文 | `ch_tra` |
| 英语 | `en` |
| 日语 | `japan` |
| 韩语 | `korean` |
| 阿拉伯语 | `arabic` |
| 印地语 | `hindi` |
| 泰语 | `thai` |
| 越南语 | `vietnam` |
| 法语 | `fr` |
| 德语 | `german` |
| 西班牙语 | `spanish` |
| 葡萄牙语 | `portuguese` |
| 意大利语 | `italian` |
| 俄语 | `russian` |
| 波兰语 | `polish` |
| 土耳其语 | `turkish` |
| 乌克兰语 | `ukrainian` |
| 罗马尼亚语 | `romanian` |
| 荷兰语 | `dutch` |
| 塞尔维亚语（拉丁） | `serbian_latin` |
| 克罗地亚语 | `croatian` |
| 保加利亚语 | `bulgarian` |
| 捷克语 | `czech` |
| 丹麦语 | `danish` |
| 芬兰语 | `finnish` |
| 挪威语 | `norwegian` |
| 斯洛文尼亚语 | `slovenian` |
| 瑞典语 | `swedish` |
| 匈牙利语 | `hungarian` |
| 斯洛伐克语 | `slovak` |

**语系包：**

| 语系 | 代码 |
|------|------|
| 拉丁语系 | `latin` |
| 阿拉伯语系 | `arabic` |
| 斯拉夫语系（西里尔） | `cyrillic` |
| 斯拉夫语系（拉丁） | `devanagari` |
| 天城文 | `cyrillic` |

---

*文档来源：https://mineru.net/apiManage/docs*