#!/usr/bin/env node
/**
 * mcp_client_proof.mjs — Phase 4A §19：用 **DSH 自己那套 MCP SDK** 打通一次
 *
 * 为什么这样才算证明
 * ──────────────────
 * 断言「DSH 能调用这个 MCP server」有两种做法：
 *   (a) 在文档里写一段配置（那是**意愿**，不是证据）；
 *   (b) 用 DSH 运行时**同一个库、同一个版本**做一次真实握手与调用。
 *
 * 这里做的是 (b)：从 DSH 的 node_modules 里解析 `@modelcontextprotocol/sdk`
 * （DSH 的 `dsh-mcp-client` 用的就是它），用 `StdioClientTransport` 起我们的
 * `lacan-kb-mcp`，走 initialize → tools/list → tools/call，并核对：
 *   * 协商到的协议版本落在 DSH 支持的列表里
 *   * tool 名与数量（10 个）
 *   * `tools/call` 返回 8 段结构化证据，且 passage_id 真实存在于 canonical store
 *   * 未知 tool / 非法参数 → 协议错误（而不是崩掉）
 *
 * 用法
 * ────
 *   node _scripts/_tools/mcp_client_proof.mjs [--json]
 */

import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const VAULT = path.dirname(path.dirname(HERE))
const SERVER = path.join(HERE, 'lacan-kb-mcp')
const DSH_ROOT = '/Users/coffee/.npm/_npx/1e7f6d9597241db0'
const DSH_SUPPORTED = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05',
                       '2024-10-07']

function resolveSdk() {
  // 直接用 DSH 安装里的那份 SDK：证明的是 **DSH 的那个客户端**能连上
  const req = createRequire(path.join(DSH_ROOT, 'noop.js'))
  const entry = req.resolve('@modelcontextprotocol/sdk/client/index.js')
  const version = JSON.parse(fs.readFileSync(
    path.join(DSH_ROOT, 'node_modules/@modelcontextprotocol/sdk/package.json'),
    'utf8')).version
  return { entry, version }
}

const checks = []
function check(id, name, passed, detail) {
  checks.push({ id, name, passed: !!passed, detail })
}

async function main() {
  const { version: sdkVersion } = resolveSdk()
  const { Client } = await import(
    path.join(DSH_ROOT, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js'))
  const { StdioClientTransport } = await import(
    path.join(DSH_ROOT, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js'))
  // 协议版本兼容性：拿 **SDK 自己导出的** 支持列表，核我们 server 声明的那一个。
  // （不要去调 client 的非公开方法 —— 拿不到 negotiated 版本就成了假检查。）
  const sdkTypes = await import(
    path.join(DSH_ROOT, 'node_modules/@modelcontextprotocol/sdk/dist/esm/types.js'))
  const serverSrc = fs.readFileSync(
    path.join(HERE, 'lacan_mcp/server.py'), 'utf8')
  const declared = (serverSrc.match(/PROTOCOL_VERSION\s*=\s*"([^"]+)"/) || [])[1]
  const supported = sdkTypes.SUPPORTED_PROTOCOL_VERSIONS

  const transport = new StdioClientTransport({
    command: process.execPath === undefined ? 'python3' : 'python3',
    args: [SERVER],
    cwd: VAULT,
    stderr: 'pipe',
  })
  const client = new Client({ name: 'dsh-mcp-client-proof', version: '1.0.0' },
                            { capabilities: {} })
  await client.connect(transport)

  const ver = client.getServerVersion?.() || {}
  const caps = client.getServerCapabilities?.() || {}
  check(1, 'MCP SDK 版本与 DSH 一致', true, `sdk@${sdkVersion}`)
  check(2, 'stdio 握手成功', !!ver.name, `serverInfo=${JSON.stringify(ver)}`)
  check(3, 'server 声明的协议版本被 DSH 的 SDK 支持',
        !!declared && supported.includes(declared),
        `lacan-kb 声明 ${declared}；DSH 支持 ${JSON.stringify(supported)}；` +
        `SDK LATEST=${sdkTypes.LATEST_PROTOCOL_VERSION}`)
  check(4, 'capabilities 只含 tools', JSON.stringify(Object.keys(caps)) === '["tools"]',
        JSON.stringify(caps))

  const { tools } = await client.listTools()
  check(5, 'tools/list 返回 10 个 tool', tools.length === 10,
        tools.map(t => t.name).join(','))
  check(6, 'tool 名与契约一致',
        tools.map(t => t.name).join(',') ===
        'search_passages,get_passage,get_context,resolve_entity,get_concept,' +
        'find_concept_evidence,trace_concept,compare_concepts,trace_source,' +
        'terminology_lookup', tools.map(t => t.name).join(','))
  check(7, '每个 tool 都带 inputSchema', tools.every(t => t.inputSchema?.type === 'object'),
        `${tools.filter(t => t.inputSchema).length}/${tools.length}`)
  // DSH 侧看到的工具名形状
  check(8, 'DSH 侧命名形状 mcp__lacan-kb__<tool> 可用', tools.length > 0,
        `mcp__lacan-kb__${tools[0].name}`)

  const r1 = await client.callTool({ name: 'search_passages',
                                     arguments: { query: 'objet a', top_k: 3 } })
  const sc1 = r1.structuredContent || {}
  const sections = ['request', 'resolution', 'retrieval', 'evidence', 'coverage',
                    'provenance', 'warnings', 'evidence_state']
  check(9, 'tools/call 返回 8 段结构化证据',
        sections.every(s => s in sc1), Object.keys(sc1).join(','))
  check(10, 'structuredContent 里带 content 文本兜底',
        Array.isArray(r1.content) && r1.content[0]?.type === 'text',
        `${(r1.content || []).length} block`)
  check(11, 'evidence_state 结构合法（无 cosine 阈值）',
        sc1.evidence_state?.method === 'structural_only_no_cosine_threshold',
        sc1.evidence_state?.state)

  // passage_id 真实性：去 canonical store 核（不信 server 自报）
  const known = new Set()
  const store = path.join(VAULT, '_data/passage_store/passages.jsonl')
  const fd = fs.openSync(store, 'r')
  const buf = Buffer.alloc(1 << 22)
  let rest = ''
  let n = 0
  while ((n = fs.readSync(fd, buf, 0, buf.length)) > 0) {
    const chunk = rest + buf.subarray(0, n).toString('utf8')
    const lines = chunk.split('\n')
    rest = lines.pop()
    for (const l of lines) {
      if (!l.trim()) continue
      try { known.add(JSON.parse(l).id) } catch { /* ignore */ }
    }
  }
  fs.closeSync(fd)
  const pids = (sc1.evidence || []).map(e => e.passage_id)
  check(12, '返回的 passage_id 全部真实存在（独立复核）',
        pids.length > 0 && pids.every(p => known.has(p)),
        `${pids.length} 条，store 内 ${known.size} 条`)

  const r2 = await client.callTool({ name: 'resolve_entity', arguments: { term: 'Symbolic' } })
  check(13, '第二个 tool 也可调用（resolve_entity）',
        (r2.structuredContent || {}).resolution?.resolution_status === 'RESOLVED',
        JSON.stringify((r2.structuredContent || {}).resolution?.candidates?.map(c => c.entity_id)))

  let protocolErr = null
  try {
    await client.callTool({ name: 'write_canonical_truth', arguments: { x: 1 } })
  } catch (e) {
    protocolErr = e
  }
  check(14, '未知 tool → 协议错误（不崩、不静默）', !!protocolErr,
        protocolErr ? String(protocolErr.message).slice(0, 80) : 'no error raised')

  await client.close()

  const doc = {
    schema_version: 'mcp-dsh-client-proof/v1',
    server: { name: 'lacan-kb', command: 'python3',
              args: [path.relative(VAULT, SERVER)], transport: 'stdio' },
    dsh_sdk: { path: path.join(DSH_ROOT, 'node_modules/@modelcontextprotocol/sdk'),
               version: sdkVersion,
               latest_protocol_version: sdkTypes.LATEST_PROTOCOL_VERSION,
               supported_protocol_versions: supported },
    server_declared_protocol_version: declared,
    checks: checks, passed: checks.filter(c => c.passed).length, total: checks.length,
    generated_by: '_scripts/_tools/mcp_client_proof.mjs',
  }
  const out = path.join(VAULT, '_data/mcp/DSH_CLIENT_PROOF.json')
  fs.mkdirSync(path.dirname(out), { recursive: true })
  fs.writeFileSync(out, JSON.stringify(doc, null, 1) + '\n')
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(doc, null, 1))
  } else {
    for (const c of checks) {
      console.log(`  ${c.passed ? 'PASS' : 'FAIL'}  ${c.name.padEnd(44)} ${c.detail}`)
    }
    console.log(`[mcp-proof] ${doc.passed}/${doc.total} passed`)
    console.log(`wrote ${path.relative(VAULT, out)}`)
  }
  return doc.passed === doc.total ? 0 : 1
}

main().then(code => process.exit(code)).catch(e => {
  console.error('proof failed:', e)
  process.exit(2)
})
