#!/usr/bin/env python3
"""Patch vrcompositor's scene shader on this headset to cut soft circles, placed in output pixels.

Works on the user's own copy of the shader. Stores premultiplied (rgb*a, a); the compositor's camera pass blends
passthrough with ONE_MINUS_DST_ALPHA wherever a < 1.

Refuses any shader other than the one the ids below were read from, because SteamVR updates can renumber them.

usage: gen_circle_spv.py <stock.spv> <out.spv> --centers x,y[,x,y...] [--radius R] [--soft S]
       gen_circle_spv.py --check <stock.spv>     exit 0 if this shader can be patched
"""
import argparse
import hashlib
import os
import subprocess
import sys
import tempfile

STOCK_SHA256 = "f28dd5d22a570cbee64057da03d0418b80aee88a8eeed988b2f776e8d9a513f2"

# Ids from `spirv-dis --raw-id` of that shader.
GLSL = "%1"
T_FLOAT, T_VEC2, T_VEC3, T_VEC4 = "%8", "%39", "%30", "%9"
FRAG_COORD = "%487"       # Input vec4, declared in the interface, unused by stock
RGB = "%911"              # final tinted rgb
OUTPUT = "%504"
STORE = "OpStore %504 %994"
FUNC = "%4 = OpFunction %2 None %3"


def fl(x):
    return repr(float(x))


def build_patch(centers, radius, soft):
    consts = [
        f"%mk_f1 = OpConstant {T_FLOAT} 1",
        f"%mk_soft = OpConstant {T_FLOAT} {fl(soft)}",
        f"%mk_r0 = OpConstant {T_FLOAT} {fl(radius)}",
    ]
    code = [
        f"%mk_fc = OpLoad {T_VEC4} {FRAG_COORD}",
        f"%mk_xy = OpVectorShuffle {T_VEC2} %mk_fc %mk_fc 0 1",
        f"%mk_r = OpCopyObject {T_FLOAT} %mk_r0",
        f"%mk_e0 = OpFSub {T_FLOAT} %mk_r %mk_soft",
        f"%mk_e1 = OpFAdd {T_FLOAT} %mk_r %mk_soft",
    ]

    alpha = "%mk_f1"
    for i, (cx, cy) in enumerate(centers):
        consts += [
            f"%mk_cx{i} = OpConstant {T_FLOAT} {fl(cx)}",
            f"%mk_cy{i} = OpConstant {T_FLOAT} {fl(cy)}",
            f"%mk_c{i} = OpConstantComposite {T_VEC2} %mk_cx{i} %mk_cy{i}",
        ]
        code += [
            f"%mk_d{i} = OpExtInst {T_FLOAT} {GLSL} Distance %mk_xy %mk_c{i}",
            f"%mk_s{i} = OpExtInst {T_FLOAT} {GLSL} SmoothStep %mk_e0 %mk_e1 %mk_d{i}",
            f"%mk_m{i} = OpExtInst {T_FLOAT} {GLSL} FMin {alpha} %mk_s{i}",
        ]
        alpha = f"%mk_m{i}"

    code += [
        f"%mk_rgb = OpVectorTimesScalar {T_VEC3} {RGB} {alpha}",
        f"%mk_o0 = OpCompositeExtract {T_FLOAT} %mk_rgb 0",
        f"%mk_o1 = OpCompositeExtract {T_FLOAT} %mk_rgb 1",
        f"%mk_o2 = OpCompositeExtract {T_FLOAT} %mk_rgb 2",
        f"%mk_out = OpCompositeConstruct {T_VEC4} %mk_o0 %mk_o1 %mk_o2 {alpha}",
        f"OpStore {OUTPUT} %mk_out",
    ]
    return consts, code


def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        try:
            return 0 if sha256_of(sys.argv[2]) == STOCK_SHA256 else 3
        except OSError:
            return 3
    ap = argparse.ArgumentParser()
    ap.add_argument("stock")
    ap.add_argument("out")
    ap.add_argument("--centers", required=True, help="x,y[,x,y...] in output pixels")
    ap.add_argument("--radius", type=float, default=400)
    ap.add_argument("--soft", type=float, default=40)
    args = ap.parse_args()

    nums = [float(v) for v in args.centers.split(",")]
    if not nums or len(nums) % 2:
        sys.exit("--centers needs x,y pairs")
    centers = list(zip(nums[0::2], nums[1::2]))
    if args.soft <= 0:
        sys.exit("--soft must be > 0")

    digest = sha256_of(args.stock)
    if digest != STOCK_SHA256:
        sys.exit(f"stock shader changed (sha256 {digest}); re-check the ids before patching")

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "stock.spvasm")
        dst = os.path.join(tmp, "patched.spvasm")
        subprocess.run(["spirv-dis", "--raw-id", args.stock, "-o", src], check=True)
        with open(src) as fh:
            asm = fh.read()
        for marker in (STORE, FUNC):
            if asm.count(marker) != 1:
                sys.exit(f"unexpected shader layout: {marker}")

        consts, code = build_patch(centers, args.radius, args.soft)
        asm = asm.replace(FUNC, "\n".join(consts) + "\n" + FUNC)
        asm = asm.replace(STORE, "\n".join(code))
        with open(dst, "w") as fh:
            fh.write(asm)
        subprocess.run(["spirv-as", "--target-env", "vulkan1.1", dst, "-o", args.out], check=True)
        subprocess.run(["spirv-val", "--target-env", "vulkan1.1", args.out], check=True)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
