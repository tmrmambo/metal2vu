import os
import kc
import macho

JOBS = [
    ('out/payload.005/System__Library__KernelCollections__SystemKernelExtensions.kc', [
        'com.apple.driver.AppleParavirtGPU',
        'com.apple.iokit.IOAcceleratorFamily2',
        'com.apple.iokit.IOGraphicsFamily',
        'com.apple.iokit.IOGPUFamily',
        'com.apple.AppleGraphicsDeviceControl',
    ]),
    ('out/payload.006/System__Library__KernelCollections__BootKernelExtensions.kc', [
        'com.apple.iokit.IOSurface',
        'com.apple.iokit.IOPCIFamily',
    ]),
]

OUT = 'kexts'
os.makedirs(OUT, exist_ok=True)

for path, names in JOBS:
    buf = open(path, 'rb').read()
    ents = {n: (vm, fo) for n, vm, fo in kc.fileset_entries(buf)}
    for n in names:
        if n not in ents:
            print('MISSING', n, 'in', path)
            continue
        vm, fo = ents[n]
        info = kc.entry_info(buf, fo)
        dst = os.path.join(OUT, n)
        size = kc.extract(buf, fo, dst)
        d = macho.describe(dst)
        s = d['slices'][0]
        print('%s\n  from %s  fileoff=%#x vmaddr=%#x' % (n, os.path.basename(path), fo, vm))
        print('  kc-entry uuid %s' % info['uuid'])
        print('  out %d bytes  arch=%s sub=%s type=%s uuid=%s' % (
            size, s['cputype'], s['cpusubtype'], s['filetype'], s['uuid']))
        print('  sha256 %s' % macho.sha256(dst))
        for sg in info['segments']:
            print('    seg %-14s vm=%#012x/%#x file=%#x/%#x' % (sg[0], sg[1], sg[2], sg[3], sg[4]))
    del buf
