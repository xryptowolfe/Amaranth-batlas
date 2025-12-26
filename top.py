from amaranth import *


class BooleanAtlas10Ops(Elaboratable):
    """
    GenesisAI-compatible beta core (pol2/pol3) with 10 operators.
    Works in plain Elaboratable style (no wiring.Component signature requirements).
    """

    # Operator IDs
    OP_AND    = 0
    OP_OR     = 1
    OP_IMPLY  = 2
    OP_CONV   = 3
    OP_XOR    = 4
    OP_XNOR   = 5
    OP_NAND   = 6
    OP_NOR    = 7
    OP_NIMPLY = 8
    OP_INV    = 9

    def __init__(self, n_nibbles: int, k: int, count_width: int = 32):
        assert 1 <= n_nibbles <= 32
        assert k in (2, 3)

        self.N = n_nibbles
        self.K = k
        self.CW = count_width

        # IO signals (plain Amaranth)
        self.start  = Signal()            # input
        self.busy   = Signal()            # output
        self.done   = Signal()            # output

        self.data_in = Signal(4 * n_nibbles)  # input packed nibbles

        self.rd_addr = Signal(4)          # input
        self.rd_data = Signal(count_width)  # output

    @staticmethod
    def _apply_op(m: Module, op_sel: Value, a: Value, b: Value, out: Signal):
        """10 GenesisAI ops on 4-bit vectors."""
        with m.Switch(op_sel):
            with m.Case(BooleanAtlas10Ops.OP_AND):
                m.d.comb += out.eq(a & b)
            with m.Case(BooleanAtlas10Ops.OP_OR):
                m.d.comb += out.eq(a | b)
            with m.Case(BooleanAtlas10Ops.OP_IMPLY):
                m.d.comb += out.eq((~a) | b)          # a -> b
            with m.Case(BooleanAtlas10Ops.OP_CONV):
                m.d.comb += out.eq((~b) | a)          # b -> a
            with m.Case(BooleanAtlas10Ops.OP_XOR):
                m.d.comb += out.eq(a ^ b)
            with m.Case(BooleanAtlas10Ops.OP_XNOR):
                m.d.comb += out.eq(~(a ^ b))
            with m.Case(BooleanAtlas10Ops.OP_NAND):
                m.d.comb += out.eq(~(a & b))
            with m.Case(BooleanAtlas10Ops.OP_NOR):
                m.d.comb += out.eq(~(a | b))
            with m.Case(BooleanAtlas10Ops.OP_NIMPLY):
                m.d.comb += out.eq(a & (~b))          # ~(a->b)
            with m.Case(BooleanAtlas10Ops.OP_INV):
                m.d.comb += out.eq(b & (~a))          # ~(b->a)
            with m.Default():
                m.d.comb += out.eq(a ^ b)

    def elaborate(self, platform):
        m = Module()

        N = self.N
        K = self.K
        CW = self.CW

        # Unpack nibbles
        nibbles = [self.data_in[4*i:4*i+4] for i in range(N)]

        # Histogram RAM
        mem = Memory(width=CW, depth=16, init=[0] * 16)
        m.submodules.wr = wr = mem.write_port(granularity=CW)
        m.submodules.rd = rd = mem.read_port(domain="sync")

        # Internal/external read mux
        use_internal_read = Signal()
        int_rd_addr = Signal(4)
        m.d.comb += rd.addr.eq(Mux(use_internal_read, int_rd_addr, self.rd_addr))
        m.d.comb += self.rd_data.eq(rd.data)

        # Gosper mask enumerator for K-subsets
        mask = Signal(N, reset=0)
        init_mask = (1 << K) - 1
        last_mask = ((1 << K) - 1) << (N - K)

        neg_mask = Signal(N)
        c = Signal(N)
        r = Signal(N + 1)
        x_xor_r = Signal(N + 1)
        tz = Signal(range(N))
        next_mask = Signal(N)
        temp = Signal(N + 1)

        m.d.comb += neg_mask.eq((~mask + 1)[:N])
        m.d.comb += c.eq(mask & neg_mask)
        m.d.comb += r.eq(mask + c)
        m.d.comb += x_xor_r.eq(r ^ mask)

        with m.Switch(c):
            for i in range(N):
                with m.Case(1 << i):
                    m.d.comb += tz.eq(i)
            with m.Default():
                m.d.comb += tz.eq(0)

        m.d.comb += temp.eq(x_xor_r >> 2)
        m.d.comb += next_mask.eq(((temp >> tz) | r)[:N])

        is_last = Signal()
        m.d.comb += is_last.eq(mask == last_mask)

        # Select K elements by scanning mask
        scan_i = Signal(range(N + 1))
        sel_count = Signal(range(4))
        sel0 = Signal(4)
        sel1 = Signal(4)
        sel2 = Signal(4)

        # Operator counters
        op1 = Signal(4)  # 0..9
        op2 = Signal(4)  # 0..9

        # Compute results
        t1 = Signal(4)
        t2 = Signal(4)
        self._apply_op(m, op1, sel0, sel1, t1)
        self._apply_op(m, op2, t1,  sel2, t2)

        final_res = Signal(4)
        if K == 2:
            m.d.comb += final_res.eq(t1)
        else:
            m.d.comb += final_res.eq(t2)

        # Histogram update regs
        bin_val = Signal(4)

        # Control regs
        busy = Signal(reset=0)
        done = Signal(reset=0)
        m.d.comb += [
            self.busy.eq(busy),
            self.done.eq(done),
        ]

        # Clear loop
        clr_idx = Signal(4)

        with m.FSM(name="atlas10"):

            with m.State("IDLE"):
                m.d.sync += [
                    busy.eq(0),
                    done.eq(0),
                    wr.en.eq(0),
                    use_internal_read.eq(0),
                ]
                with m.If(self.start):
                    m.next = "CLEAR_INIT"

            with m.State("CLEAR_INIT"):
                m.d.sync += [
                    busy.eq(1),
                    clr_idx.eq(0),
                ]
                m.next = "CLEAR_STEP"

            with m.State("CLEAR_STEP"):
                m.d.sync += [
                    wr.en.eq(1),
                    wr.addr.eq(clr_idx),
                    wr.data.eq(0),
                ]
                with m.If(clr_idx == 15):
                    m.d.sync += wr.en.eq(0)
                    m.next = "INIT_ENUM"
                with m.Else():
                    m.d.sync += clr_idx.eq(clr_idx + 1)

            with m.State("INIT_ENUM"):
                m.d.sync += [
                    mask.eq(init_mask),
                    scan_i.eq(0),
                    sel_count.eq(0),
                    op1.eq(0),
                    op2.eq(0),
                ]
                m.next = "SCAN_SELECT"

            with m.State("SCAN_SELECT"):
                with m.If(scan_i < N):
                    with m.If(mask[scan_i]):
                        with m.If(sel_count == 0):
                            m.d.sync += sel0.eq(nibbles[scan_i])
                        with m.Elif(sel_count == 1):
                            m.d.sync += sel1.eq(nibbles[scan_i])
                        with m.Else():
                            m.d.sync += sel2.eq(nibbles[scan_i])
                        m.d.sync += sel_count.eq(sel_count + 1)
                    m.d.sync += scan_i.eq(scan_i + 1)
                with m.Else():
                    m.d.sync += [op1.eq(0), op2.eq(0)]
                    m.next = "DO_ONE_RESULT"

            # produce one result (either op1 for K=2, or (op1,op2) for K=3), then histogram update
            with m.State("DO_ONE_RESULT"):
                m.d.sync += [
                    bin_val.eq(final_res),
                    use_internal_read.eq(1),
                    int_rd_addr.eq(final_res),
                ]
                m.next = "HIST_READ"

            with m.State("HIST_READ"):
                # wait for sync read
                m.next = "HIST_WRITE"

            with m.State("HIST_WRITE"):
                m.d.sync += [
                    wr.en.eq(1),
                    wr.addr.eq(bin_val),
                    wr.data.eq(rd.data + 1),
                ]
                m.next = "ADVANCE"

            with m.State("ADVANCE"):
                m.d.sync += [
                    wr.en.eq(0),
                    use_internal_read.eq(0),
                ]

                if K == 2:
                    with m.If(op1 == 9):
                        m.next = "NEXT_SUBSET"
                    with m.Else():
                        m.d.sync += op1.eq(op1 + 1)
                        m.next = "DO_ONE_RESULT"
                else:
                    with m.If(op2 == 9):
                        with m.If(op1 == 9):
                            m.next = "NEXT_SUBSET"
                        with m.Else():
                            m.d.sync += [
                                op1.eq(op1 + 1),
                                op2.eq(0),
                            ]
                            m.next = "DO_ONE_RESULT"
                    with m.Else():
                        m.d.sync += op2.eq(op2 + 1)
                        m.next = "DO_ONE_RESULT"

            with m.State("NEXT_SUBSET"):
                with m.If(is_last):
                    m.d.sync += [
                        busy.eq(0),
                        done.eq(1),
                    ]
                    m.next = "DONE"
                with m.Else():
                    m.d.sync += [
                        mask.eq(next_mask),
                        scan_i.eq(0),
                        sel_count.eq(0),
                    ]
                    m.next = "SCAN_SELECT"

            with m.State("DONE"):
                with m.If(~self.start):
                    m.next = "IDLE"

        return m
