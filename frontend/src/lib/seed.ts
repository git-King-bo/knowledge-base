import type { DocumentItem, KnowledgeCategory, ProviderConfig, ProviderModel } from './types'

export const initialCategories: KnowledgeCategory[] = [
  { id: 'product', name: '产品知识', count: 2 },
  { id: 'engineering', name: '研发规范', count: 1 },
  { id: 'operations', name: '运营手册', count: 1 },
]

export const initialDocuments: DocumentItem[] = [
  {
    id: 'doc-product-overview',
    title: '知识库 MVP 范围',
    summary: '第一版先打通文档增删改查、搜索、分类、标签和模型配置。',
    content:
      '# 知识库 MVP 范围\n\n## 必做\n\n- 文档创建和编辑\n- Markdown 预览\n- 分类和标签\n- 标题、摘要、正文搜索\n- 模型提供方配置\n\n## 暂缓\n\n- 复杂权限\n- 版本对比\n- RAG 问答',
    categoryId: 'product',
    tags: ['mvp', 'planning'],
    status: 'published',
    updatedAt: '2026-08-03',
  },
  {
    id: 'doc-ai-provider',
    title: '模型 Provider 接入约定',
    summary: '模型 API 不进入业务层，通过 provider adapter 和 registry 做统一切换。',
    content:
      '# 模型 Provider 接入约定\n\n业务代码只调用统一的 AI 服务接口。\n\n```text\nchat / summarize / embed / rerank\n```\n\n新增模型时只补 adapter 和配置，不改文档业务。',
    categoryId: 'engineering',
    tags: ['ai', 'provider'],
    status: 'draft',
    updatedAt: '2026-08-03',
  },
  {
    id: 'doc-search-plan',
    title: '搜索能力演进',
    summary: 'MVP 用数据库关键字搜索，后续再引入向量索引和语义召回。',
    content:
      '# 搜索能力演进\n\n1. SQLite LIKE 或 FTS\n2. PostgreSQL 全文检索\n3. 向量库语义检索\n4. RAG 回答引用来源',
    categoryId: 'product',
    tags: ['search', 'roadmap'],
    status: 'published',
    updatedAt: '2026-08-03',
  },
]

export const initialProviders: ProviderConfig[] = [
  {
    id: 'provider-mock',
    name: 'Mock Provider',
    provider: 'mock',
    baseUrl: 'local://mock',
    apiKeyHint: '无需密钥',
    defaultModel: 'mock-chat',
    isDefault: true,
  },
  {
    id: 'provider-openai',
    name: 'OpenAI',
    provider: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyHint: '未填写',
    defaultModel: 'gpt-4.1-mini',
    isDefault: false,
  },
]

export const initialProviderModels: Record<string, ProviderModel[]> = {
  'provider-mock': [
    {
      id: 'model-mock-chat',
      providerId: 'provider-mock',
      name: 'mock-chat',
      contextWindow: 32000,
      supportsTools: true,
      supportsVision: false,
      status: 'ready',
    },
  ],
  'provider-openai': [
    {
      id: 'model-gpt-4-1-mini',
      providerId: 'provider-openai',
      name: 'gpt-4.1-mini',
      contextWindow: 1000000,
      supportsTools: true,
      supportsVision: true,
      status: 'draft',
    },
  ],
}
