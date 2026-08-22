import readline from "node:readline";
import {
  AndroidAppInfo,
  AndroidBot,
  AndroidSessionStore,
  AndroidSignProvider,
  AndroidUrlSignProvider,
  CoroutineScope,
  LogLevel,
  NopLogHandler,
} from "@acidify/core";

const EMPTY = new Int8Array(0);

export function encodeVarint(value) {
  let current = BigInt(value);
  if (current < 0n) throw new Error("negative protobuf varint");
  const bytes = [];
  do {
    let next = Number(current & 0x7fn);
    current >>= 7n;
    if (current !== 0n) next |= 0x80;
    bytes.push(next);
  } while (current !== 0n);
  return Uint8Array.from(bytes);
}

function concat(...parts) {
  const length = parts.reduce((total, part) => total + part.length, 0);
  const output = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function fieldVarint(field, value) {
  return concat(encodeVarint(field << 3), encodeVarint(value));
}

function fieldBytes(field, value) {
  const bytes = value instanceof Uint8Array ? value : Uint8Array.from(value);
  return concat(encodeVarint((field << 3) | 2), encodeVarint(bytes.length), bytes);
}

export function packOidb(command, service, body, clientVersion = "Android 9.2.80.13690") {
  return concat(
    fieldVarint(1, command),
    fieldVarint(2, service),
    fieldBytes(4, body),
    fieldBytes(6, new TextEncoder().encode(clientVersion)),
  );
}

function readVarint(bytes, start) {
  let value = 0n;
  let shift = 0n;
  let offset = start;
  while (offset < bytes.length && shift <= 63n) {
    const byte = bytes[offset++];
    value |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return [value, offset];
    shift += 7n;
  }
  throw new Error("invalid protobuf varint");
}

export function unpackOidb(bytes) {
  const fields = new Map();
  let offset = 0;
  while (offset < bytes.length) {
    const [tag, afterTag] = readVarint(bytes, offset);
    offset = afterTag;
    const field = Number(tag >> 3n);
    const wire = Number(tag & 7n);
    if (wire === 0) {
      const [value, afterValue] = readVarint(bytes, offset);
      fields.set(field, value);
      offset = afterValue;
    } else if (wire === 2) {
      const [length, afterLength] = readVarint(bytes, offset);
      offset = afterLength;
      const end = offset + Number(length);
      if (end > bytes.length) throw new Error("truncated protobuf field");
      fields.set(field, bytes.slice(offset, end));
      offset = end;
    } else {
      throw new Error(`unsupported protobuf wire type ${wire}`);
    }
  }
  const result = Number(fields.get(3) ?? 0n);
  const errorBytes = fields.get(5) ?? EMPTY;
  const error = new TextDecoder().decode(errorBytes);
  if (result !== 0) throw new Error(`QQ server error ${result}${error ? `: ${error}` : ""}`);
  const body = fields.get(4);
  if (!(body instanceof Uint8Array) || body.length === 0) {
    throw new Error("QQ server returned an empty OIDB body");
  }
  return body;
}

function unsignedProvider() {
  const unavailable = async () => {
    throw new Error("Android signer is not configured");
  };
  return {
    [AndroidSignProvider.Symbol]: true,
    sign: unavailable,
    energy: unavailable,
    getDebugXwid: unavailable,
  };
}

export class AcidifyRuntime {
  constructor() {
    this.scope = new CoroutineScope(true);
    this.bot = null;
    this.store = null;
  }

  init(sessionJson, signUrl = "") {
    const parsed = JSON.parse(sessionJson);
    if (String(parsed.password ?? "") !== "") {
      throw new Error("session import must not contain a QQ password");
    }
    this.store = AndroidSessionStore.Companion.fromJson(sessionJson);
    this.store.password = "";
    const signer = signUrl
      ? new AndroidUrlSignProvider(this.scope, signUrl)
      : unsignedProvider();
    this.bot = AndroidBot.create(
      AndroidAppInfo.Bundled.AndroidPhone_9_2_80,
      this.store,
      signer,
      this.scope,
      LogLevel.INFO,
      NopLogHandler.getInstance(),
    );
    return { uin: this.store.uin.toString(), protocol_version: "9.2.80" };
  }

  async online() {
    if (!this.bot) throw new Error("runtime is not initialized");
    await this.bot.online(false);
    return { uin: this.bot.uin.toString(), session_json: this.store.toJson() };
  }

  async friends() {
    if (!this.bot?.isLoggedIn) throw new Error("Android session is not online");
    return (await this.bot.fetchFriends()).map((friend) => ({
      uin: friend.uin.toString(),
      nickname: friend.nickname,
      remark: friend.remark,
      category_id: friend.categoryId,
    }));
  }

  async oidb(commandName, command, service, bodyBase64) {
    if (!this.bot?.isLoggedIn) throw new Error("Android session is not online");
    const body = Uint8Array.from(Buffer.from(bodyBase64, "base64"));
    const envelope = packOidb(command, service, body);
    const response = await this.bot.unsafeSendPacket(commandName, envelope, 10000n);
    if (response.retCode !== 0) {
      throw new Error(`SSO error ${response.retCode}${response.extra ? `: ${response.extra}` : ""}`);
    }
    return Buffer.from(unpackOidb(response.response)).toString("base64");
  }

  async close() {
    if (this.bot?.isLoggedIn) await this.bot.offline();
    this.scope.cancel();
  }
}

async function main() {
  const runtime = new AcidifyRuntime();
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of input) {
    if (!line.trim()) continue;
    let request;
    try {
      request = JSON.parse(line);
      let data;
      switch (request.method) {
        case "init": data = runtime.init(request.session_json, request.sign_url); break;
        case "online": data = await runtime.online(); break;
        case "friends": data = { friends: await runtime.friends() }; break;
        case "oidb": data = { body_base64: await runtime.oidb(request.command_name, request.command, request.sub_command, request.body_base64) }; break;
        case "close": data = await runtime.close(); break;
        default: throw new Error("unknown bridge method");
      }
      process.stdout.write(`${JSON.stringify({ id: request.id, ok: true, ...data })}\n`);
    } catch (error) {
      process.stdout.write(`${JSON.stringify({ id: request?.id, ok: false, error: String(error?.message ?? error) })}\n`);
    }
  }
}

if (process.argv[1]?.replaceAll("\\", "/").endsWith("/bridge.mjs")) {
  main().catch((error) => {
    process.stderr.write(`${String(error?.stack ?? error)}\n`);
    process.exitCode = 1;
  });
}
