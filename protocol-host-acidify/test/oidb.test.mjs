import test from "node:test";
import assert from "node:assert/strict";
import { packOidb, unpackOidb } from "../bridge.mjs";

test("OIDB envelope round trip", () => {
  const body = Uint8Array.from([1, 2, 3, 4]);
  const packed = packOidb(38369, 0, body);
  assert.deepEqual(Array.from(unpackOidb(packed)), Array.from(body));
});

test("OIDB server errors are preserved", () => {
  const response = Uint8Array.from([0x18, 0x3f, 0x2a, 0x03, 0x62, 0x61, 0x64]);
  assert.throws(() => unpackOidb(response), /QQ server error 63: bad/);
});
