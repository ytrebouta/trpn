"""Benchmarks for trpn: dmath, FmtVal and the stack pane's drawing.

Marked bench: a plain pytest run skips them (pyproject.toml), as their budgets depend on the
machine. Run them with pytest -m bench, or directly:

	python tests\test_benchmark.py

Each test measures a group of operations, prints a table and checks each time against a budget.
A time is the best of REPEAT rounds, each round long enough (ROUND_S) to smooth the timer: the best
round is the least disturbed by the rest of the machine. The median round is printed too.

Budgets are 4 to 25 times the best times measured when the suite was written (dmath: 2026-10-20,
Windows 10, Python 3.14, about 12 µs for exp 0.7 at 28 digits), so a failure means a real slowdown,
not noise. The exact shortcut log10 1000 has a tight budget, about 7 times its time: losing it
multiplies its time by about 16, which fails clearly. On a much slower machine, scale them all.
The frame budget at 60 fps is 16.7 ms: drawing the stack and formatting its values must stay a
small part of it.
"""

import random
import statistics
import sys
from decimal import Decimal as D, Context
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN, ROUND_DOWN, ROUND_UP
from decimal import ROUND_FLOOR, ROUND_CEILING, ROUND_05UP
from time import perf_counter, perf_counter_ns

import pytest

from trpn import dmath
from trpn.calculator import FmtVal, RpnCalculator

import test_dmath_exp as ref

pytestmark	= pytest.mark.bench								# skipped by a plain pytest run
STG_CTX		= Context(prec=28, rounding=ROUND_HALF_UP)				# the calculator's stack arithmetic
REPEAT		= 5
ROUND_S		= 0.02									# seconds per round at least
FRAME_MS	= 1000 / 60


# --- harness ---------------------------------------------------------------------------------

def measure(call):
	"""(best, median) time per call in µs over REPEAT rounds, after one warm-up call."""

	call()
	start	= perf_counter()
	call()
	single	= max(perf_counter() - start, 1e-7)
	number	= max(1, int(ROUND_S / single))

	rounds = []
	for _ in range(REPEAT):
		start_ns = perf_counter_ns()
		for _ in range(number):
			call()
		rounds.append((perf_counter_ns() - start_ns) / number / 1000)

	return min(rounds), statistics.median(rounds)


def run_table(title, rows):
	"""rows: (label, call, budget µs). Prints the table, returns the rows over budget."""

	print(f"      {title}")
	print(f"        {'':44} {'best µs':>10} {'median µs':>10} {'budget µs':>10}")
	over = []
	for label, call, budget in rows:
		best, median = measure(call)
		flag = '' if best <= budget else '  OVER'
		print(f"        {label:44} {best:10.1f} {median:10.1f} {budget:10.0f}{flag}")
		if best > budget:
			over.append((label, round(best, 1), budget))
	return over


# --- dmath -----------------------------------------------------------------------------------

def test_bench_functions():
	"""Every dmath function on typical arguments at 28 digits (the calculator's precision)."""

	ctx		= STG_CTX
	rng		= random.Random('bench')
	reals	= [ctx.create_decimal(repr(rng.uniform(-10, 10))) for _ in range(50)]
	pos		= [ctx.create_decimal(repr(rng.uniform(0.01, 100))) for _ in range(50)]
	rows	= [
		('exp    x in (-10, 10)  ×50', lambda: [dmath.exp(x, ctx=ctx) for x in reals], 50 * 80),
		('ln     x in (0.01, 100)  ×50', lambda: [dmath.ln(x, ctx=ctx) for x in pos], 50 * 150),
		('log10  x in (0.01, 100)  ×50', lambda: [dmath.log10(x, ctx=ctx) for x in pos], 50 * 150),
		('yˣ     y in (0.01, 100), x = 2.5  ×50', lambda: [dmath.power(y, D('2.5'), ctx=ctx) for y in pos], 50 * 900),
		('ˣ√y    y in (0.01, 100), x = 3  ×50', lambda: [dmath.root(y, D(3), ctx=ctx) for y in pos], 50 * 900),
	]
	over_ = run_table('dmath, 28 digits: 50 calls per row', rows)
	assert not over_, over_


def test_bench_argument_classes():
	"""By kind of argument: tiny, extreme exponents, overflow, exact results and their shortcuts.
	yˣ and ˣ√y always run the exactness check first: exact results cost as much as the others."""

	ctx		= STG_CTX
	quiet	= Context(prec=28, traps=[])											# overflow as a flag
	rows	= [
		('exp 1E-20', lambda: dmath.exp(D('1E-20'), ctx=ctx), 50),
		('exp 1E-999999', lambda: dmath.exp(D('1E-999999'), ctx=ctx), 50),
		('exp 2302585 (2.0E+999999, at the limit)', lambda: dmath.exp(D(2302585), ctx=ctx), 100),
		('exp 1E30 (overflow, settled before computing)', lambda: dmath.exp(D('1E30'), ctx=quiet), 30),
		('ln 1 + 1E-27', lambda: dmath.ln(D('1.000000000000000000000000001'), ctx=ctx), 50),
		('ln 1E999999', lambda: dmath.ln(D('1E999999'), ctx=ctx), 50),
		('log10 1000 (exact shortcut)', lambda: dmath.log10(D(1000), ctx=ctx), 10),
		('log10 7', lambda: dmath.log10(D(7), ctx=ctx), 150),
		('yˣ 2^10 (exact)', lambda: dmath.power(D(2), D(10), ctx=ctx), 500),
		('yˣ 4^0.5 (exact)', lambda: dmath.power(D(4), D('0.5'), ctx=ctx), 500),
		('yˣ 1.5^2.25', lambda: dmath.power(D('1.5'), D('2.25'), ctx=ctx), 700),
		('yˣ 10^-30000 (exact, power of ten)', lambda: dmath.power(D(10), D(-30000), ctx=ctx), 300),
		('yˣ 7^20000', lambda: dmath.power(D(7), D(20000), ctx=ctx), 800),
		('yˣ (-2)^41', lambda: dmath.power(D(-2), D(41), ctx=ctx), 500),
		('ˣ√y ³√8 (exact)', lambda: dmath.root(D(8), D(3), ctx=ctx), 500),
		('ˣ√y ³√10', lambda: dmath.root(D(10), D(3), ctx=ctx), 300),
		('ˣ√y ³√-27 (exact)', lambda: dmath.root(D(-27), D(3), ctx=ctx), 500),
		('ˣ√y 999999th root of 1E999999 (exact)', lambda: dmath.root(D('1E999999'), D(999999), ctx=ctx), 250),
	]
	over_ = run_table('dmath by argument', rows)
	assert not over_, over_


def test_bench_precisions():
	"""How the cost grows with the precision: 12 to 200 digits."""

	# budgets (exp 0.7, ln 7, yˣ 1.5^2.25) in µs for each precision
	budgets = {12: (60, 100, 600), 28: (80, 150, 700), 50: (120, 200, 1000), 100: (150, 300, 2000),
			   200: (2000, 1000, 6000)}
	rows = []
	for prec, (b_exp, b_ln, b_pow) in budgets.items():
		ctx = Context(prec=prec)
		rows.append((f"exp 0.7       prec {prec}", (lambda c=ctx: dmath.exp(D('0.7'), ctx=c)), b_exp))
		rows.append((f"ln 7          prec {prec}", (lambda c=ctx: dmath.ln(D(7), ctx=c)), b_ln))
		rows.append((f"yˣ 1.5^2.25   prec {prec}", (lambda c=ctx: dmath.power(D('1.5'), D('2.25'), ctx=c)), b_pow))
	over_ = run_table('dmath by precision', rows)
	assert not over_, over_


def test_bench_rounding_modes():
	"""The rounding mode must not change the cost: exp 0.7 at 28 digits in every mode."""

	modes = (ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN, ROUND_DOWN, ROUND_UP,
			 ROUND_FLOOR, ROUND_CEILING, ROUND_05UP)
	rows = [(f"exp 0.7  {mode}", (lambda c=Context(prec=28, rounding=mode): dmath.exp(D('0.7'), ctx=c)), 80)
			for mode in modes]
	over_ = run_table('dmath by rounding mode', rows)
	assert not over_, over_


def test_bench_ziv_retries():
	"""How often the Ziv loop needs a second try at 28 digits with 8 guard digits: retries cost a
	full recomputation, so they must stay rare. Counted over the random sweeps of test_dmath_exp."""

	tries		= []
	decided		= dmath._decided

	def counting(y, err, wp, ctx):
		result = decided(y, err, wp, ctx)
		tries.append(result)
		return result

	dmath._decided = counting
	try:
		calls = 0
		for name in ('exp', 'ln', 'log10', 'power', 'root'):
			function = getattr(dmath, name)
			for args in ref.sweep_cases(name):
				function(*args, ctx=Context(prec=28))
				calls += 1
	finally:
		dmath._decided = decided

	retries		= tries.count(False)
	rate		= retries / calls
	print(f"      Ziv loop: {calls} calls, {len(tries)} tries, {retries} retries ({rate:.2%} of calls)")
	assert rate < 0.01, rate													# measured: 0 retries in 300 calls


# --- FmtVal and the stack pane ------------------------------------------------------------------

def stack_values():
	"""The 16-level test stack: every kind of display case."""

	stg = Context(prec=28)
	return [
		D('0'), D('55'), D('-123.45'), stg.divide(D(2), D(3)), stg.multiply(stg.divide(D(1), D(3)), D(3)),
		stg.divide(D(355), D(113)), D('9.87654321E-5'), D('-0.0000799999999'), D('1000000'), D('-123456789'),
		D('12345678901234567890123'), stg.power(D(2), 200), D('1.5E-25'), D('-.5'), D('999.6'), D('124567.89'),
	]


def test_bench_fmtval():
	"""FmtVal.run on the 16 test values at several widths: full precision fits, candidates, ####."""

	values	= stack_values()
	fv		= FmtVal()
	rows	= []
	for width in (36, 20, 12, 8, 3):
		rows.append((f"16 values, width {width}", (lambda w=width: [fv.run(v, 20, w) for v in values]), 16 * 60))
	over_ = run_table('FmtVal: one stack of 16 values per row', rows)
	assert not over_, over_


class StubTerm:
	"""move_xy as blessed writes it for an xterm-like terminal: CSI row;col H."""

	def move_xy(self, x, y):
		return f"\x1b[{y + 1};{x + 1}H"


def stack_calc(w, h, stack):
	"""A calculator whose stack pane is w × h: draw_stack takes its geometry from Maupertuis."""

	calc				= RpnCalculator()
	calc.ini()
	calc.term			= StubTerm()
	calc.mp.build(w, h + 6)									# the other panes take 6 rows
	calc.data['stack']	= stack
	return calc


def draw_call(calc):
	"""One redraw of calc's stack pane, at its own geometry."""

	x0, y0, w, h = calc.mp.panes['stack']
	return lambda: calc.draw_stack(x0, y0, w, h)


def test_bench_draw_stack():
	"""RpnCalculator.draw_stack: one full redraw of the stack pane, at several pane sizes, against
	the 60 fps frame budget (16.7 ms)."""

	big_stack	= [D(i) / D(7) for i in range(1, 101)]
	wide		= stack_calc(80, 20, stack_values())
	medium		= stack_calc(40, 20, stack_values())
	narrow		= stack_calc(12, 20, stack_values())
	tall		= stack_calc(200, 100, big_stack)
	rows = [
		('16 levels, pane 80×20', draw_call(wide), 2000),
		('16 levels, pane 40×20', draw_call(medium), 2000),
		('16 levels, pane 12×20 (narrow)', draw_call(narrow), 2000),
	]
	over_ = run_table('draw_stack: one redraw per row', rows)

	rows = [('100 levels, pane 200×100', draw_call(tall), 10000)]
	over_ += run_table('draw_stack: a tall terminal', rows)

	best, _ = measure(draw_call(tall))
	share	= best / 1000 / FRAME_MS
	print(f"      tallest redraw: {best / 1000:.2f} ms = {share:.0%} of a 60 fps frame")
	assert not over_, over_


def test_bench_session():
	"""A typical keypress: one dmath operation, then the stack pane redrawn (16 levels, 80 wide)."""

	calc		= stack_calc(80, 20, stack_values())
	redraw		= draw_call(calc)
	operations	= [lambda x: dmath.ln(x, ctx=STG_CTX), lambda x: dmath.exp(x, ctx=STG_CTX),
				   lambda x: dmath.power(x, D('2.5'), ctx=STG_CTX)]

	def keypress():
		for operation in operations:
			calc.data['stack'][-1] = operation(D('0.7'))
			redraw()

	over_ = run_table('keypress: operation + redraw, 3 per row', [('ln, eˣ, yˣ with redraws', keypress, 3 * 2000)])
	assert not over_, over_


# --- runner ---------------------------------------------------------------------------------

if __name__ == '__main__':
	tests	= [(name, fn) for name, fn in globals().items() if name.startswith('test_') and callable(fn)]
	failed	= 0
	for name, fn in tests:
		start = perf_counter()
		try:
			fn()
			print(f"PASS  {name}  ({perf_counter() - start:.1f} s)")
		except AssertionError as err:
			failed += 1
			print(f"FAIL  {name}: {err}")
	print(f"\n{len(tests) - failed}/{len(tests)} passed")
	sys.exit(1 if failed else 0)
