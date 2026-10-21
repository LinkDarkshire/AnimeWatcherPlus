/** What an admin device's "add device" QR code holds. */
export interface PairingQr {
  awp: 1
  server: string
  code: string
}

export function pairingQrText(server: string, code: string): string {
  const payload: PairingQr = { awp: 1, server, code }
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
