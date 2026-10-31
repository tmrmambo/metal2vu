# macOS 26.7.2 x86_64 Framework Analysis Manifest

## Scope

- Build: `25G325`
- Product: macOS Tahoe `26.7.2`
- Architecture: `x86_64`
- Source tier: BaseSystem dyld shared cache
- Status: static `KNOWN`; not target guest `TESTED`

These samples do not prove byte identity with installed SystemOS.

The installed SystemOS IOGPU image remains unavailable.

## Raw extracts

| File | Bytes | SHA-256 | UUID |
|---|---:|---|---|
| `raw/Metal` | 5,723,760 | `9BAB47CD9A7E11E15A17486C8E4BA2775CDDC1A705A6F60A39C0A87D9F598C9D` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` |
| `raw/IOAccelerator` | 78,856 | `7EF85F8415B13992A34FDDDF0B523D8D4DA366564E93D78187D8E0BC5BF01FA2` | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` |

## Analysis inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| `analysis-input/Metal` | 6,356,568 | `AFD31CC024908EC448914F0B54C5EF213AC6CCAE570A45C406384749A5AA63D9` |
| `analysis-input/IOAccelerator` | 79,400 | `A2E859A54796D6C440C108E43E3926AD9A138B7D52DB934C17357317F255BF09` |
| `analysis-input/libsystem_sandbox.dylib` | 58,696 | `9D83CCD7471C035DF20B80313915335E62FA1A1358F958DB95A90FA05FB54C1E` |
| `analysis-input/SkyLight` | 8,227,280 | `40A54C61E89D66734565BD3E105899C7D2F5676F373A6A1EC28FBACDF2561195` |
| `metal-objc.json` | 1,946,692 | `F3577E664A0E68A89F33691F483697C5738F3A7DE5DE936856F2C6ED14F01BC5` |

Raw Metal and IOAccelerator files are the report hash anchors.

Analysis inputs are separate parsing copies.

## Persistent IDA databases

| IDB | Bytes | SHA-256 | Key annotation |
|---|---:|---|---|
| `idb/Metal-BaseSystem-analysis.i64` | 60,887,653 | `B8F9A4AFAB85D308F37CBC6962D0C862C3691DD2C8919C87C88659040F7D36DF` | registration chain and `newFunctionWithName:` ABI |
| `idb/IOAccelerator-BaseSystem-analysis.i64` | 1,005,286 | `AB85F84D2052652C6BC4D017C8060C751459E42ABDEAD08E055FB65EEDCAD5BA` | type-5 open and selectors 9/2/0/7 |
| `idb/libsystem_sandbox-BaseSystem-analysis.i64` | 626,152 | `E39BF92450ED8F57F574CB442E4AD471F1F62D7C6225FCE66804BB5AD118C762` | GPU bundle paths and trust gate |
| `idb/SkyLight-BaseSystem-analysis.i64` | 88,026,862 | `87E3F40EAB2B1C122A493132DF27126A8BA6C19A9E574715522B25D34B734E03` | display accelerator to default Metal device |

## Direct ABI evidence

`MTLLibrary` required-instance list:

- List: `0x7FF80B3A46D8`
- `newFunctionWithName:` record: `0x7FF80B3A46F8`
- Type string: `0x7FF80B44B975`
- Encoding: `@24@0:8@16`

IOAccelerator creation entry:

- Function: `IOAccelDeviceCreateWithAPIProperty`
- Address: `0x7FF80B170F60`
- UserClient type: `5`
- Required selectors: `2`, `0`
- Optional or ignored selectors: `7`, `9`

## Related contracts

- `../../../spec-work/metal-registration-contract.md`
- `../../../spec-work/bridge-runtime-contract.md`
- `../../../macos26-guest-metal-driver-spec.md`

## Missing evidence

- installed SystemOS `dyld_shared_cache_x86_64*`
- installed SystemOS `IOGPU.framework`
- target guest framework trace
- target `/Library/GPUBundles` trust result
