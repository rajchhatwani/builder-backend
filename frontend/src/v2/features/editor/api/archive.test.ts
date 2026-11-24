// @vitest-environment node
import { expect, it } from 'vitest'
import { readKit } from './archive'

it('opens the deflated UTF-8 text in the server ZIP and removes the slug prefix', async () => {
  const zip = new Blob([Buffer.from('UEsDBBQAAAAIAGQjeV3jGM1KFQAAABMAAAAaAAAAbGVhdmUtcmVxdWVzdHMvYXBwL21haW4ucHkrKMrMK9FQSjm8MuvwAoWyUiVNLgBQSwMEFAAAAAgAZCN5XQAAAAACAAAAAAAAABgAAABsZWF2ZS1yZXF1ZXN0cy9lbXB0eS50eHQDAFBLAQIUAxQAAAAIAGQjeV3jGM1KFQAAABMAAAAaAAAAAAAAAAAAAACAAQAAAABsZWF2ZS1yZXF1ZXN0cy9hcHAvbWFpbi5weVBLAQIUAxQAAAAIAGQjeV0AAAAAAgAAAAAAAAAYAAAAAAAAAAAAAACAAU0AAABsZWF2ZS1yZXF1ZXN0cy9lbXB0eS50eHRQSwUGAAAAAAIAAgCOAAAAhQAAAAAA', 'base64')])
  expect(await readKit(zip)).toEqual(new Map([['app/main.py', 'print("déjà vu")\n'], ['empty.txt', '']]))
})
