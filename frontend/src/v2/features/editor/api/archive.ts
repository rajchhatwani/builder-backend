const localFile = 0x04034b50
const centralDirectory = 0x02014b50
const maxFileBytes = 4 * 1024 * 1024
const maxArchiveBytes = 64 * 1024 * 1024

/**
 * The self-host endpoint emits a deterministic ZIP of UTF-8 text under one
 * slug, with sizes in the local headers and no data descriptors.
 */
export async function readKit(archive: Blob): Promise<Map<string, string>> {
  if (archive.size > maxArchiveBytes) throw new Error('kit_size')
  const bytes = await archive.arrayBuffer()
  const view = new DataView(bytes)
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })
  const files = new Map<string, string>()
  let position = 0
  let total = 0
  while (view.getUint32(position, true) === localFile) {
    const flags = view.getUint16(position + 6, true)
    const method = view.getUint16(position + 8, true)
    const crc = view.getUint32(position + 14, true)
    const compressedSize = view.getUint32(position + 18, true)
    const size = view.getUint32(position + 22, true)
    const nameSize = view.getUint16(position + 26, true)
    const extraSize = view.getUint16(position + 28, true)
    const nameStart = position + 30
    const start = nameStart + nameSize + extraSize
    const end = start + compressedSize
    total += size
    if ((flags & 9) !== 0 || method !== 8 || end > bytes.byteLength || size > maxFileBytes || total > maxArchiveBytes) {
      throw new Error('kit_entry')
    }
    const [root, ...parts] = decoder.decode(bytes.slice(nameStart, nameStart + nameSize)).split('/')
    if (!root || !parts.length || parts.some(part => !part || part === '..' || part === '.')) throw new Error('kit_path')
    const path = parts.join('/')
    if (files.has(path)) throw new Error('kit_duplicate')
    // ZIP stores raw deflate. Wrap it in gzip to use the browser API's
    // original format support and validate the entry checksum as it inflates.
    const header = Uint8Array.of(31, 139, 8, 0, 0, 0, 0, 0, 0, 255)
    const trailer = new DataView(new ArrayBuffer(8))
    trailer.setUint32(0, crc, true)
    trailer.setUint32(4, size, true)
    const stream = new Blob([header, bytes.slice(start, end), trailer.buffer]).stream()
    const unpacked = stream.pipeThrough(new DecompressionStream('gzip')).getReader()
    const contents = new Uint8Array(size)
    let offset = 0
    try {
      for (;;) {
        const chunk = await unpacked.read()
        if (chunk.done) break
        contents.set(chunk.value, offset)
        offset += chunk.value.byteLength
      }
    } finally {
      await unpacked.cancel()
    }
    if (offset !== size) throw new Error('kit_size')
    files.set(path, decoder.decode(contents))
    position = end
  }
  if (view.getUint32(position, true) !== centralDirectory) throw new Error('kit_directory')
  return files
}
