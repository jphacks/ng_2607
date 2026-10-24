// The official OAuth client handles discovery, PAR, PKCE, DPoP and token refresh.
// Python talks to this process over a private JSON-lines stdin/stdout channel.
import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import { NodeOAuthClient, buildAtprotoLoopbackClientMetadata } from '@atproto/oauth-client-node'
import { Agent, RichText } from '@atproto/api'

const port = Number(process.env.PORT || 8765)
const file = path.join(process.cwd(), 'data', 'oauth_sessions.json')
const chatAudience = 'did:web:api.bsky.chat#bsky_chat'
const dmScope = [
  'atproto',
  `rpc:chat.bsky.convo.getConvoForMembers?aud=${chatAudience}`,
  `rpc:chat.bsky.convo.sendMessage?aud=${chatAudience}`,
  `rpc:chat.bsky.convo.getMessages?aud=${chatAudience}`,
]
const playerScope = dmScope.join(' ')
const characterScope = [
  ...dmScope,
  `rpc:chat.bsky.convo.listConvos?aud=${chatAudience}`,
  `rpc:chat.bsky.convo.getConvoAvailability?aud=${chatAudience}`,
  // Automation (automation.py): DM polling, read receipts, scheduled posts and Pinksky stories (image uploads).
  `rpc:chat.bsky.convo.getLog?aud=${chatAudience}`,
  `rpc:chat.bsky.convo.updateRead?aud=${chatAudience}`,
  'repo:app.bsky.feed.post?action=create',
  'blob:image/*',
].join(' ')

fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
try { fs.chmodSync(path.dirname(file), 0o700) } catch {}
let saved = { states: {}, sessions: {} }
if (fs.existsSync(file)) saved = JSON.parse(fs.readFileSync(file, 'utf8'))
function persist() {
  const temporary = `${file}.${process.pid}.tmp`
  fs.writeFileSync(temporary, JSON.stringify(saved), { mode: 0o600 })
  fs.renameSync(temporary, file)
  fs.chmodSync(file, 0o600)
}
const store = (kind) => ({
  async get(key) { return saved[kind][key] },
  async set(key, value) { saved[kind][key] = value; persist() },
  async del(key) { delete saved[kind][key]; persist() },
})
const oauth = new NodeOAuthClient({
  clientMetadata: buildAtprotoLoopbackClientMetadata({
    scope: characterScope,
    redirect_uris: [`http://127.0.0.1:${port}/oauth/callback`],
  }),
  stateStore: store('states'),
  sessionStore: store('sessions'),
})

async function agentFor(did) {
  const session = await oauth.restore(did)
  if (!session || session.did !== did) throw new Error('OAuth セッションがありません。再認証してください')
  return new Agent(session)
}

async function run(command) {
  switch (command.op) {
    case 'ping': return { ok: true }
    case 'publicGet': {
      const url = new URL(command.url)
      if (url.origin !== 'https://public.api.bsky.app' || !url.pathname.startsWith('/xrpc/app.bsky.')) {
        throw new Error('Public AppView URL is not allowed')
      }
      const response = await fetch(url, {
        headers: { Accept: 'application/json', 'User-Agent': 'ReAlLoveSimulator/0.1' },
        redirect: 'manual',
        signal: AbortSignal.timeout(15000),
      })
      if (!response.ok) throw new Error(`Public AppView returned HTTP ${response.status}`)
      const body = await response.text()
      if (body.length > 2_000_000) throw new Error('Public AppView response is too large')
      return { data: JSON.parse(body) }
    }
    case 'authorize': {
      const scope = command.role === 'character' ? characterScope : playerScope
      const url = await oauth.authorize(command.handle, { state: command.state, scope })
      return { url: String(url) }
    }
    case 'callback': {
      const { session, state } = await oauth.callback(new URLSearchParams(command.query))
      const { scope } = await session.getTokenInfo(false)
      return { did: session.did, state, scope }
    }
    case 'restore': {
      await agentFor(command.did)
      return { did: command.did }
    }
    case 'scope': {
      const session = await oauth.restore(command.did)
      const { scope } = await session.getTokenInfo(false)
      return { scope }
    }
    case 'forget': {
      await store('sessions').del(command.did)
      return { ok: true }
    }
    case 'convos': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      const result = await chat.chat.bsky.convo.listConvos({ limit: 100, ...(command.cursor ? { cursor: command.cursor } : {}) })
      return { convos: result.data.convos, cursor: result.data.cursor || null }
    }
    case 'messages': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      const result = await chat.chat.bsky.convo.getMessages({ convoId: command.convoId, limit: 100, ...(command.cursor ? { cursor: command.cursor } : {}) })
      return { messages: result.data.messages, cursor: result.data.cursor || null }
    }
    case 'convoForPlayer': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      const result = await chat.chat.bsky.convo.getConvoAvailability({ members: [command.playerDid] })
      return { convo: result.data.convo || null }
    }
    case 'convoWithMember': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      const result = await chat.chat.bsky.convo.getConvoForMembers({ members: [command.memberDid] })
      return { convo: result.data.convo }
    }
    case 'sendMessage': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      try {
        const result = await chat.chat.bsky.convo.sendMessage({ convoId: command.convoId, message: { text: command.text } })
        return { message: result.data }
      } catch (error) {
        // A definite 4xx response means the chat service rejected the write.
        if (Number.isInteger(error?.status) && error.status >= 400 && error.status < 500) {
          return { rejected: String(error?.message || error) }
        }
        throw error
      }
    }
    case 'chatLog': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      const result = await chat.chat.bsky.convo.getLog(command.cursor ? { cursor: command.cursor } : {})
      return { logs: result.data.logs, cursor: result.data.cursor || null }
    }
    case 'updateRead': {
      const chat = (await agentFor(command.did)).withProxy('bsky_chat', 'did:web:api.bsky.chat')
      await chat.chat.bsky.convo.updateRead({ convoId: command.convoId })
      return { ok: true }
    }
    case 'createPost': {
      const agent = await agentFor(command.did)
      const rt = new RichText({ text: command.text })
      // Links and hashtags only: mentions would need handle resolution outside the granted scopes.
      rt.detectFacetsWithoutResolution()
      const facets = (rt.facets || []).filter(facet => facet.features.every(feature => feature.$type !== 'app.bsky.richtext.facet#mention'))
      const result = await agent.post({ text: rt.text, langs: ['ja'], ...(facets.length ? { facets } : {}) })
      return { uri: result.uri, cid: result.cid }
    }
    case 'createStory': {
      // A Pinksky/Pinkleap story is a Bluesky image post carrying the story tag.
      const agent = await agentFor(command.did)
      const upload = await agent.uploadBlob(Buffer.from(command.image, 'base64'), { encoding: command.mime })
      const result = await agent.post({
        text: command.text, langs: ['ja'], tags: [command.tag],
        embed: {
          $type: 'app.bsky.embed.images',
          images: [{ image: upload.data.blob, alt: command.alt, aspectRatio: { width: command.width, height: command.height } }],
        },
      })
      return { uri: result.uri, cid: result.cid }
    }
    default: throw new Error('Unknown operation')
  }
}

for await (const line of readline.createInterface({ input: process.stdin })) {
  try {
    const result = await run(JSON.parse(line))
    process.stdout.write(JSON.stringify({ result }) + '\n')
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: String(error?.message || error) }) + '\n')
  }
}
