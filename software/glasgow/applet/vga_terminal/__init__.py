import logging
import argparse
import os
from migen import *

from .. import *
from ..vga_output import VGAOutputApplet


class VGATerminalSubtarget(Module):
    def __init__(self, vga, h_active, v_active, font_data, font_width, font_height, blink_cyc,
                 char_mem_init=[], attr_mem_init=[]):
        char_mem = Memory(width=8, depth=(h_active // font_width) * (v_active // font_height),
                          init=char_mem_init)
        attr_mem = Memory(width=5, depth=char_mem.depth,
                          init=attr_mem_init)
        self.specials += [char_mem, attr_mem]

        char_rdport = char_mem.get_port(has_re=True, clock_domain="pix")
        attr_rdport = attr_mem.get_port(has_re=True, clock_domain="pix")
        self.specials += [char_rdport, attr_rdport]

        char_ctr   = Signal(max=char_mem.depth)
        char_l_ctr = Signal.like(char_ctr)
        char_data  = Signal.like(char_rdport.dat_r)
        attr_data  = Signal.like(attr_rdport.dat_r)
        self.comb += [
            char_rdport.re.eq(1),
            char_rdport.adr.eq(char_ctr),
            char_data.eq(char_rdport.dat_r),
            attr_rdport.re.eq(1),
            attr_rdport.adr.eq(char_ctr),
            attr_data.eq(attr_rdport.dat_r),
        ]

        font_mem = Memory(width=font_width, depth=font_height * 256, init=font_data)
        self.specials += font_mem

        font_rdport = font_mem.get_port(has_re=True, clock_domain="pix")
        self.specials += font_rdport

        font_h_ctr = Signal(max=font_width)
        font_v_ctr = Signal(max=font_height)
        font_line  = Signal(font_width)
        font_shreg = Signal.like(font_line)
        attr_reg   = Signal.like(attr_data)
        undrl_reg  = Signal()
        self.comb += [
            font_rdport.re.eq(1),
            font_rdport.adr.eq(char_data * font_height + font_v_ctr),
            font_line.eq(Cat(reversed([font_rdport.dat_r[n] for n in range(font_width)])))
        ]
        self.sync.pix += [
            If(vga.v_stb,
                char_ctr.eq(0),
                char_l_ctr.eq(0),
                font_v_ctr.eq(0),
                font_h_ctr.eq(0),
            ).Elif(vga.h_stb & vga.v_en,
                If(font_v_ctr == font_height - 1,
                    char_l_ctr.eq(char_ctr),
                    font_v_ctr.eq(0),
                ).Else(
                    char_ctr.eq(char_l_ctr),
                    font_v_ctr.eq(font_v_ctr + 1),
                ),
                font_h_ctr.eq(0),
            ).Elif(vga.v_en & vga.h_en,
                If(font_h_ctr == 0,
                    char_ctr.eq(char_ctr + 1)
                ),
                If(font_h_ctr == font_width - 1,
                    font_h_ctr.eq(0),
                ).Else(
                    font_h_ctr.eq(font_h_ctr + 1),
                )
            ),
            If(~vga.h_en | (font_h_ctr == font_width - 1),
                font_shreg.eq(font_line),
                attr_reg.eq(attr_data),
                undrl_reg.eq(font_v_ctr == font_height - 1),
            ).Else(
                font_shreg.eq(font_shreg[1:])
            )
        ]

        blink_ctr = Signal(max=blink_cyc)
        blink_reg = Signal()
        self.sync.pix += [
            If(blink_ctr == blink_cyc - 1,
                blink_ctr.eq(0),
                blink_reg.eq(~blink_reg),
            ).Else(
                blink_ctr.eq(blink_ctr + 1),
            )
        ]

        pix_fg = Signal()
        self.comb += [
            pix_fg.eq((font_shreg[0] | (undrl_reg & attr_reg[3])) & (~attr_reg[4] | blink_reg)),
            vga.pix.r.eq(pix_fg & attr_reg[0]),
            vga.pix.g.eq(pix_fg & attr_reg[1]),
            vga.pix.b.eq(pix_fg & attr_reg[2]),
        ]


class VGATerminalApplet(VGAOutputApplet, name="vga-terminal"):
    logger = logging.getLogger(__name__)
    help = "emulate a teleprinter using a VGA monitor"
    description = """
    TBD
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        parser.add_argument(
            "-fd", "--font-data", metavar="FILE", type=argparse.FileType("rb"),
            default=os.path.join(os.path.dirname(__file__), "ibmvga8x16.bin"),
            help="load character generator ROM from FILE (default: ibmvga8x16.bin)")
        parser.add_argument(
            "-fw", "--font-width", metavar="PX", type=int, default=8,
            help="set font width to PX pixels (default: %(default)s)")
        parser.add_argument(
            "-fh", "--font-height", metavar="PX", type=int, default=16,
            help="set font height to PX pixels (default: %(default)s)")

    def build(self, target, args):
        vga = super().build(target, args, test_pattern=False)
        iface = self.mux_interface

        subtarget = iface.add_subtarget(VGATerminalSubtarget(
            vga=vga,
            h_active=args.h_active,
            v_active=args.v_active,
            font_data=args.font_data.read(),
            font_width=args.font_width,
            font_height=args.font_height,
            blink_cyc=int(args.pix_clk_freq * 1e6 / 2),
            char_mem_init=
                b"Hello world! " +
                b"0123456789" * 120 +
                b"    imgay",
            attr_mem_init=
                [0x7] * 13 +
                (list(range(9,16)) + list(range(1,8))) * 86 +
                [16|3,16|5,16|7,16|5,16|3],
        ))

# -------------------------------------------------------------------------------------------------

class VGATerminalAppletTestCase(GlasgowAppletTestCase, applet=VGATerminalApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "B"])