from amaranth.sim import Simulator, Tick
from itertools import combinations
from collections import Counter

from top import BooleanAtlas10Ops
from utils import hex_to_nibbles_le, pack_nibbles_le


# GenesisAI-compatible 10 ops on 4-bit integers (bitwise)
def op_AND(a,b):    return a & b
def op_OR(a,b):     return a | b
def op_IMPLY(a,b):  return ((~a) & 0xF) | b
def op_CONV(a,b):   return ((~b) & 0xF) | a
def op_XOR(a,b):    return a ^ b
def op_XNOR(a,b):   return (~(a ^ b)) & 0xF
def op_NAND(a,b):   return (~(a & b)) & 0xF
def op_NOR(a,b):    return (~(a | b)) & 0xF
def op_NIMPLY(a,b): return (a & ((~b) & 0xF)) & 0xF
def op_INV(a,b):    return (b & ((~a) & 0xF)) & 0xF

OPS = [op_AND, op_OR, op_IMPLY, op_CONV, op_XOR, op_XNOR, op_NAND, op_NOR, op_NIMPLY, op_INV]


def python_pol2_hist(nibbles, k=2):
    assert k == 2
    hist = [0]*16
    for i,j in combinations(range(len(nibbles)), 2):
        a = nibbles[i]
        b = nibbles[j]
        for op in OPS:
            hist[op(a,b)] += 1
    return hist


def python_pol3_hist(nibbles, k=3):
    assert k == 3
    hist = [0]*16
    for i,j,k in combinations(range(len(nibbles)), 3):
        a = nibbles[i]
        b = nibbles[j]
        c = nibbles[k]
        for op1 in OPS:
            first = op1(a,b)
            for op2 in OPS:
                hist[op2(first, c)] += 1
    return hist


def run_case(X_HEX="A1F3", K=2):
    nibbles = hex_to_nibbles_le(X_HEX)
    N = len(nibbles)
    x_packed = pack_nibbles_le(nibbles)

    dut = BooleanAtlas10Ops(n_nibbles=N, k=K, count_width=32)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        yield dut.data_in.eq(x_packed)

        # start pulse
        yield dut.start.eq(1)
        yield Tick()
        yield dut.start.eq(0)

        # run until done (cycle budget depends on N,K)
        for _ in range(5_000_000):
            if (yield dut.done):
                break
            yield Tick()
        else:
            raise RuntimeError("Timeout waiting for done")

        # read histogram bins
        hw = []
        for addr in range(16):
            yield dut.rd_addr.eq(addr)
            yield Tick()  # sync read latency
            hw.append((yield dut.rd_data))

        # reference
        if K == 2:
            ref = python_pol2_hist(nibbles, k=2)
        else:
            ref = python_pol3_hist(nibbles, k=3)

        print(f"\nX={X_HEX}  N={N}  K={K}")
        print("bin : hw  ref")
        for i in range(16):
            print(f"{i:02d}  : {hw[i]}  {ref[i]}")
        assert hw == ref, "Mismatch HW vs Python reference!"

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    run_case("A1F3", K=2)
    run_case("A1F3", K=3)
