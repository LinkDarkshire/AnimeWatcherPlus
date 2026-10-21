/** What an admin device's "add device" QR code holds. */
export interface PairingQr {
  awp: 1
  server: string
  code: string
  /** The server's certificate as the admin device knows it: a phone that
   * sees a different one is talking to someone else. */
  cert?: string
}

export function pairingQrText(server: string, code: string, cert: string | null): string {
  const payload: PairingQr = { awp: 1, server, code, ...(cert ? { cert } : {}) }
  return JSON.stringify(payload)
}

export function parsePairingQr(text: string): PairingQr | null {
  try {
    const value = JSON.parse(text)
    if (value?.awp === 1 && typeof value.server === "string" && typeof value.code === "string") return value
  } catch {
    // not ours
  }
  return null
}
