"""Tests for trpn.dmath's exponentials and powers: exp, ln, log10, power (yˣ) and root (ˣ√y).

Runs with pytest, or directly:

	python tests\test_dmath_exp.py

The reference is independent of Decimal's exp(), ln() and log10(): integer fixed point with
G = 160 decimals. ln m (1 <= m <= 10) takes six square roots, then the atanh series
2·(z + z³/3 + ...) with z = (v − 1)/(v + 1); exp t is 10^k × e^r, r = t − k·ln 10 in [0, ln 10),
by its Taylor series. Its relative error stays around 1E-150: rounding it to 50 digits or less gives
the correctly rounded value. Exact results (4^0.5 = 2) are tested on their own and kept out of the
random sweeps: there, the reference's 1.999...9 would round differently from the exact 2 in the
directed modes.
"""

import random
import sys
from decimal import Decimal as D, Context, localcontext, getcontext, setcontext, InvalidOperation
from decimal import Overflow, Underflow, Inexact, Rounded, Subnormal, Clamped, DivisionByZero
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN, ROUND_UP, ROUND_FLOOR, ROUND_DOWN
from decimal import ROUND_CEILING, ROUND_05UP
from fractions import Fraction
from math import isqrt
from time import perf_counter

from trpn import dmath

ROUNDINGS	= (ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN, ROUND_DOWN, ROUND_UP,
			   ROUND_FLOOR, ROUND_CEILING, ROUND_05UP)
G		= 160							# decimals of the fixed point
ONE		= 10 ** G
PRECS	= (12, 28, 50)
SEED	= 'exp'


# --- reference: integer fixed point, G decimals -----------------------------------------------

def ref_ln_mantissa(v):
	"""ln(v / ONE) × ONE for 1 <= v / ONE <= 10: six square roots bring v near 1, then atanh."""

	for _ in range(6):
		v = isqrt(v * ONE)											# fixed-point square root
	z		= (v - ONE) * ONE // (v + ONE)
	z2		= z * z // ONE
	term	= z
	total	= 0
	k		= 1
	while term:
		total	+= term // k
		term	= term * z2 // ONE
		k		+= 2
	return 2 * total * 64											# ln v = 2·atanh(z), times 2⁶


LN10 = ref_ln_mantissa(10 * ONE)


def ref_ln(x):
	"""ln x × ONE for a positive Decimal x: ln(mantissa) + adjusted·ln 10."""

	sign, digits, exponent	= x.as_tuple()
	n						= len(digits)
	adjusted				= exponent + n - 1
	mantissa				= int(''.join(map(str, digits))) * 10 ** (G - (n - 1))	# exact: n <= 50
	return ref_ln_mantissa(mantissa) + adjusted * LN10


def scale(x, fixed):
	"""x × fixed for a Decimal x and a fixed-point integer, as a fixed-point integer."""

	sign, digits, exponent	= x.as_tuple()
	coefficient				= int(''.join(map(str, digits)))
	if sign:
		coefficient = -coefficient
	if exponent >= 0:
		return coefficient * fixed * 10 ** exponent
	return coefficient * fixed // 10 ** -exponent


def divide(fixed, x):
	"""fixed / x for a fixed-point integer and a nonzero Decimal x, as a fixed-point integer."""

	sign, digits, exponent	= x.as_tuple()
	coefficient				= int(''.join(map(str, digits)))
	if sign:
		coefficient = -coefficient
	if exponent <= 0:
		return fixed * 10 ** -exponent // coefficient
	return fixed // (coefficient * 10 ** exponent)


def ref_exp_fixed(t):
	"""e^(t / ONE) as an exact Decimal: 10^k × e^r, r = t − k·ln 10 in [0, ln 10)."""

	k		= t // LN10
	r		= t - k * LN10
	term	= ONE
	total	= ONE
	n		= 1
	while term:
		term	= term * r // (ONE * n)
		total	+= term
		n		+= 1
	return D(f"{total}E{k - G}")


def reference(name, args):
	"""Exact Decimal close to the true value (relative error around 1E-150)."""

	if name == 'exp':
		return ref_exp_fixed(scale(args[0], ONE))
	if name == 'ln':
		return D(f"{ref_ln(args[0])}E-{G}")
	if name == 'log10':
		return D(f"{ref_ln(args[0]) * ONE // LN10}E-{G}")

	y, x		= args
	log			= ref_ln(y.copy_abs())
	if name == 'power':
		t		= scale(x, log)
		odd		= y < 0 and Fraction(x).numerator % 2 == 1
	else:
		t		= divide(log, x)
		odd		= y < 0
	value = ref_exp_fixed(t)
	return value.copy_negate() if odd else value


def rounded(value, ctx):
	"""value rounded in ctx, from the exact reference Decimal."""

	return ctx.plus(value)


# --- cases ------------------------------------------------------------------------------------

def random_decimal(rng, low_exp, high_exp, max_digits=30):
	"""Positive random Decimal, 1 to max_digits digits, magnitude 10^low_exp to 10^high_exp."""

	n		= rng.randint(1, max_digits)
	digits	= str(rng.randint(1, 9)) + ''.join(str(rng.randint(0, 9)) for _ in range(n - 1))
	exp		= rng.randint(low_exp, high_exp) - (n - 1)
	return D(f"{digits}E{exp}")


def looks_exact(name, args):
	"""True when the reference, rounded to 60 digits, has 55 significant digits or fewer: the true
	value is then an exact decimal (1/5E-14 = 2E+13), which the 1.999...9 of the reference would
	round wrongly in the directed modes. Independent of dmath."""

	value		= Context(prec=60).plus(reference(name, args))
	m, e		= dmath_free_coefficient(value)
	return len(str(m)) <= 55


def dmath_free_coefficient(d):
	"""(m, e) with d = m × 10^e and m not divisible by 10 (the test's own copy, not dmath's)."""

	sign, digits, exponent	= d.as_tuple()
	m						= int(''.join(map(str, digits)))
	e						= exponent
	while m and m % 10 == 0:
		m	//= 10
		e	+= 1
	return m, e


def sweep_cases(name, count=60):
	"""Random arguments per function, exact results excluded."""

	rng		= random.Random(f"{SEED}-{name}")
	cases	= []
	while len(cases) < count:
		if name == 'exp':
			x = random_decimal(rng, -100, 2)
			if rng.random() < 0.5:
				x = x.copy_negate()
			cases.append((x,))
		elif name in ('ln', 'log10'):
			if rng.random() < 0.2:											# close to 1
				x = D(1) + random_decimal(rng, -40, -2)
			else:
				x = random_decimal(rng, -300, 300)
			if name == 'log10' and dmath._coefficient(x)[0] == 1:
				continue
			cases.append((x,))
		elif name == 'power':
			y = random_decimal(rng, -3, 3)
			x = random_decimal(rng, -2, 1, max_digits=6)
			if rng.random() < 0.5:
				x = x.copy_negate()
			if rng.random() < 0.2:											# negative base, integer power
				y = y.copy_negate()
				x = D(rng.randint(-40, 40) or 3)
			if looks_exact('power', (y, x)):								# 2^-3 = 0.125: tested apart
				continue
			cases.append((y, x))
		else:
			y = random_decimal(rng, -30, 30)
			x = random_decimal(rng, -1, 1, max_digits=5)
			if rng.random() < 0.5:
				x = x.copy_negate()
			if rng.random() < 0.2:											# negative radicand, odd index
				y = y.copy_negate()
				x = D(rng.choice((3, 5, 7, -3, 9)))
			if looks_exact('root', (y, x)):									# 1/5E-14 = 2E+13: tested apart
				continue
			cases.append((y, x))
	return cases


def against_reference(name, args, precs=PRECS):
	"""Mismatches of dmath.<name> with the reference, every precision and rounding mode."""

	function	= getattr(dmath, name)
	exact		= reference(name, args)
	bad			= []
	for prec in precs:
		for rounding in ROUNDINGS:
			ctx		= Context(prec=prec, rounding=rounding)
			want	= rounded(exact, ctx)
			got		= function(*args, ctx=ctx)
			if got != want:
				bad.append((name, [str(a) for a in args], prec, rounding, str(want), str(got)))
	return bad


def raises(call, error=InvalidOperation):

	try:
		call()
	except error:
		return True
	return False


# --- tests ------------------------------------------------------------------------------------

def test_reference_constants():
	"""The reference's ln 10 and e match their published digits."""

	ctx = Context(prec=50)
	assert ctx.plus(D(f"{LN10}E-{G}")) == D('2.3025850929940456840179914546843642076011014886288')
	assert ctx.plus(ref_exp_fixed(ONE)) == D('2.7182818284590452353602874713526624977572470937000')


def test_sweep():
	"""exp, ln, log10, power, root on random arguments, every precision and rounding mode."""

	bad = []
	for name in ('exp', 'ln', 'log10', 'power', 'root'):
		for args in sweep_cases(name):
			bad += against_reference(name, args)
	assert not bad, (len(bad), bad[:3])


def test_exact_results():
	"""Exact results in every rounding mode: the Ziv loop alone could never decide them in the
	directed modes."""

	cases = [
		('exp', ('0',), '1'), ('ln', ('1',), '0'), ('log10', ('1000',), '3'), ('log10', ('1E-25',), '-25'),
		('log10', ('0.001',), '-3'), ('log10', ('1',), '0'),
		('power', ('2', '10'), '1024'), ('power', ('2', '-3'), '0.125'), ('power', ('4', '0.5'), '2'),
		('power', ('4', '2.5'), '32'), ('power', ('1.21', '0.5'), '1.1'), ('power', ('-2', '3'), '-8'),
		('power', ('-2', '-3'), '-0.125'), ('power', ('0', '0'), '1'), ('power', ('7', '0'), '1'),
		('power', ('0', '5'), '0'), ('power', ('1', '123.456'), '1'), ('power', ('3', '40'), '12157665459056928801'),
		('root', ('8', '3'), '2'), ('root', ('1E300', '3'), '1E100'), ('root', ('-8', '3'), '-2'),
		('root', ('32', '2.5'), '4'), ('root', ('4', '-2'), '0.5'), ('root', ('1E-500000', '2'), '1E-250000'),
		('root', ('0', '3'), '0'), ('root', ('-1', '5'), '-1'), ('root', ('16', '0.5'), '256'),
	]
	bad = []
	for name, args, want in cases:
		for rounding in ROUNDINGS:
			ctx	= Context(prec=28, rounding=rounding)
			got	= getattr(dmath, name)(*[D(a) for a in args], ctx=ctx)
			if got != D(want):
				bad.append((name, args, rounding, str(got)))
	assert not bad, bad


def test_exact_shortest_form():
	"""An exact result comes back in the form an exact operation gives it: 2^10 is 1024, not
	1024.000000000000000000000000; 10^2 is 100 (as 10 × 10), not 1E+2; beyond the precision,
	³√1E300 stays 1E+100."""

	ctx = Context(prec=28)
	cases = [(dmath.power, ('2', '10'), '1024'), (dmath.power, ('-2', '3'), '-8'), (dmath.power, ('4', '0.5'), '2'),
			 (dmath.power, ('10', '2'), '100'), (dmath.power, ('10', '27'), '1000000000000000000000000000'),
			 (dmath.power, ('10', '28'), '1E+28'), (dmath.root, ('1E6', '2'), '1000'),
			 (dmath.power, ('2', '-3'), '0.125'), (dmath.root, ('8', '3'), '2'), (dmath.root, ('1E300', '3'), '1E+100'),
			 (dmath.root, ('-8', '3'), '-2')]
	bad = [(f.__name__, args, str(f(*[D(a) for a in args], ctx=ctx))) for f, args, want in cases
		   if str(f(*[D(a) for a in args], ctx=ctx)) != want]
	assert not bad, bad


def test_exact_powers_of_ten():
	"""Powers of ten with large exponents are exact too, down to the subnormals: no Inexact, no
	Underflow, and the shortest form. The exactness check once skipped them (its cost guard
	counted base 10 as a million digits for 10^-1000000), and 10^-999999 came back inexact and
	flagged as an underflow."""

	cases = [
		(dmath.power, ('10', '-999999'), '1E-999999'), (dmath.power, ('10', '-1000000'), '1E-1000000'),
		(dmath.power, ('10', '-1000026'), '1E-1000026'), (dmath.power, ('0.01', '500000'), '1E-1000000'),
		(dmath.power, ('1E5', '-200001'), '1E-1000005'), (dmath.power, ('10', '30000'), '1E+30000'),
		(dmath.power, ('10', '-30000'), '1E-30000'), (dmath.root, ('1E999999', '999999'), '10'),
	]
	bad = []
	for f, args, want in cases:
		for rounding in ROUNDINGS:
			ctx		= Context(prec=28, rounding=rounding, traps=[])
			got		= f(*[D(a) for a in args], ctx=ctx)
			flags	= [flag.__name__ for flag in (Inexact, Underflow) if ctx.flags[flag]]
			if str(got) != want or flags:
				bad.append((f.__name__, args, rounding, str(got), flags))
	assert not bad, bad


def test_huge_exponent_denominators():
	"""Exponents whose fraction has a huge denominator (1E-999999 is 1/10^999999) give a result
	next to 1, rounded to nearest. The exactness check's cost guard once converted that
	denominator to a float, and overflowed. Directed roundings are not tested: a result within
	about 1E-4100 of 1 is beyond what the Ziv loop can decide in those modes."""

	cases = [(dmath.root, ('999999', '1E999999')), (dmath.power, ('2', '1E-999999')),
			 (dmath.power, ('999999', '1E-999999')), (dmath.power, ('10', '1E-999999')), (dmath.power, ('1E5', '1E-400'))]
	bad = []
	for f, args in cases:
		for rounding in (ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN):
			got = f(*[D(a) for a in args], ctx=Context(prec=28, rounding=rounding))
			if got != 1:
				bad.append((f.__name__, args, rounding, str(got)))
	assert not bad, bad


def test_long_exact_powers():
	"""An exact result longer than the precision is rounded like any other: 3^70 has 34 digits."""

	ctx		= Context(prec=28, rounding=ROUND_DOWN)
	exact	= D(3 ** 70)
	assert dmath.power(D(3), D(70), ctx=ctx) == ctx.plus(exact)


def test_special_values():
	"""Infinities and domain errors."""

	ctx = Context(prec=28)
	assert dmath.ln(D(0), ctx=ctx) == D('-Infinity')
	assert dmath.log10(D(0), ctx=ctx) == D('-Infinity')
	assert dmath.power(D(0), D(-1), ctx=ctx) == D('Infinity')
	assert dmath.root(D(0), D(-2), ctx=ctx) == D('Infinity')
	assert dmath.exp(D('-Infinity'), ctx=ctx) == 0
	assert dmath.exp(D('Infinity'), ctx=ctx) == D('Infinity')
	for name in ('exp', 'ln', 'log10'):
		assert getattr(dmath, name)(D('NaN'), ctx=ctx).is_nan(), name
	errors = [
		lambda: dmath.ln(D(-1), ctx=ctx), lambda: dmath.log10(D('-0.5'), ctx=ctx),
		lambda: dmath.power(D(-8), D('0.5'), ctx=ctx), lambda: dmath.root(D(-8), D(2), ctx=ctx),
		lambda: dmath.root(D(-8), D('2.5'), ctx=ctx), lambda: dmath.root(D(8), D(0), ctx=ctx),
		lambda: dmath.power(D('Infinity'), D(2), ctx=ctx),
	]
	for index, call in enumerate(errors):
		assert raises(call), index


def test_range():
	"""Results beyond the exponent range overflow or underflow as Decimal does, in every mode."""

	ctx = Context(prec=28)
	assert raises(lambda: dmath.exp(D('1E30'), ctx=ctx), Overflow)
	assert raises(lambda: dmath.power(D(10), D(1000000), ctx=ctx), Overflow)
	assert raises(lambda: dmath.root(D('1E999999'), D('0.5'), ctx=ctx), Overflow)

	# with Overflow not trapped, the caller's context decides: Infinity and a flag, never an
	# exception from inside dmath (the Ziv loop's probe once trapped it)
	for call in (lambda c: dmath.exp(D('1E30'), ctx=c), lambda c: dmath.power(D(10), D(1000000), ctx=c),
				 lambda c: dmath.root(D('1E999999'), D('0.5'), ctx=c), lambda c: dmath.power(D('9.5'), D(1100000), ctx=c)):
		quiet = Context(prec=28, traps=[])
		assert call(quiet) == D('Infinity')
		assert quiet.flags[Overflow]

	nearest = Context(prec=28)
	up		= Context(prec=28, rounding=ROUND_UP)
	assert dmath.exp(D('-1E30'), ctx=nearest) == 0
	assert dmath.exp(D('-1E30'), ctx=up) == D('1E-1000026')
	assert dmath.power(D(10), D(-1000030), ctx=nearest) == 0
	assert dmath.power(D(10), D(-1000030), ctx=up) == D('1E-1000026')
	assert dmath.power(D(-10), D(-1000031), ctx=Context(prec=28, rounding=ROUND_FLOOR)) == D('-1E-1000026')

	# just inside the range: e^2302585 = 2.0E+999999 for Emax 999999, the reference agrees
	bad = against_reference('exp', (D(2302585),), precs=(28,))
	assert not bad, bad[:2]


def test_error_bounds():
	"""Every kernel's error bound covers its real error, at every working precision."""

	approx = {
		'exp':		lambda wp, a: dmath._exp_approx(wp, a[0]),
		'ln':		lambda wp, a: dmath._ln_approx(wp, a[0]),
		'log10':	lambda wp, a: dmath._log10_approx(wp, a[0]),
		'power':	lambda wp, a: dmath._power_approx(wp, a[0].copy_abs(), a[1], False, 1),
		'root':		lambda wp, a: dmath._power_approx(wp, a[0].copy_abs(), a[1], True, 1),
	}
	false_bounds	= []
	report			= []
	for name, kernel in approx.items():
		smallest = None
		for args in sweep_cases(name, 30):
			if name in ('power', 'root'):
				exact = reference(name, (args[0].copy_abs(), args[1]))
			else:
				exact = reference(name, args)
			for wp in (3, 6, 12, 29, 36, 60):
				value, bound, _ = kernel(wp, args)
				if bound.is_infinite():
					continue
				with localcontext(Context(prec=600, Emin=-9999999, Emax=9999999)):
					real = abs(value - exact)
					if real == 0:
						continue
					margin = bound / real
				if real > bound:
					false_bounds.append((name, [str(a) for a in args], wp, str(real), str(bound)))
				if smallest is None or margin < smallest[0]:
					smallest = (margin, [str(a) for a in args], wp)
		report.append((name, smallest))

	for name, (margin, args, wp) in report:
		print(f"      {name:5}  smallest margin {float(margin):9.2f}  (args {', '.join(args)}, wp {wp})")
	assert not false_bounds, (len(false_bounds), false_bounds[:3])


def test_retry_path():
	"""With 1 guard digit the Ziv loop retries, and still rounds correctly."""

	retries		= []
	decided		= dmath._decided

	def counting(y, err, wp, ctx):
		result = decided(y, err, wp, ctx)
		if not result:
			retries.append(wp)
		return result

	guard			= dmath.GUARD
	dmath.GUARD		= 1
	dmath._decided	= counting
	try:
		bad = []
		for name in ('exp', 'ln', 'power', 'root'):
			for args in sweep_cases(name, 15):
				bad += against_reference(name, args, precs=(28,))
	finally:
		dmath.GUARD		= guard
		dmath._decided	= decided
	assert not bad, bad[:3]
	assert retries, 'the loop never retried'


def test_global_context_independence():
	"""Results don't depend on the global context, even a hostile one, and leave its flags clear."""

	calls = [('exp', (D('2.5'),)), ('ln', (D('7'),)), ('log10', (D('0.002'),)), ('power', (D('1.5'), D('2.25'))),
			 ('root', (D('-27'), D(3))), ('power', (D(4), D('0.5'))), ('exp', (D('-1E30'),))]
	saved = getcontext()
	try:
		setcontext(Context(prec=28))
		baseline = [str(getattr(dmath, n)(*a, ctx=Context(prec=28))) for n, a in calls]
		hostile = Context(prec=1, rounding=ROUND_FLOOR, Emin=-3, Emax=3,
						  traps=[Inexact, Rounded, Underflow, Subnormal, Clamped, Overflow, DivisionByZero])
		setcontext(hostile)
		hostile.clear_flags()
		got = [str(getattr(dmath, n)(*a, ctx=Context(prec=28))) for n, a in calls]
		flags = [s.__name__ for s, raised in hostile.flags.items() if raised]
	finally:
		setcontext(saved)
	assert got == baseline, list(zip(got, baseline))
	assert not flags, flags


def test_global_context_untouched():
	"""Without ctx, the functions use the global context but never change its precision or
	rounding, even after an error."""

	ctx			= getcontext()
	prec		= ctx.prec
	rounding	= ctx.rounding
	dmath.exp(D('2.5'))
	dmath.power(D('1.5'), D('2.25'))
	dmath.root(D(-27), D(3))
	for call in (lambda: dmath.ln(D(-1)), lambda: dmath.root(D(-8), D(2))):
		assert raises(call)
	assert (ctx.prec, ctx.rounding) == (prec, rounding)


def test_caller_flags():
	"""Inexact is set on the caller's context for inexact results only."""

	cases = [
		(lambda c: dmath.exp(D(1), ctx=c), True), (lambda c: dmath.ln(D(2), ctx=c), True),
		(lambda c: dmath.log10(D(2), ctx=c), True), (lambda c: dmath.power(D(2), D('0.5'), ctx=c), True),
		(lambda c: dmath.root(D(2), D(3), ctx=c), True), (lambda c: dmath.exp(D(0), ctx=c), False),
		(lambda c: dmath.ln(D(1), ctx=c), False), (lambda c: dmath.log10(D('1E-25'), ctx=c), False),
		(lambda c: dmath.power(D(2), D(10), ctx=c), False), (lambda c: dmath.power(D(4), D('2.5'), ctx=c), False),
		(lambda c: dmath.root(D(-8), D(3), ctx=c), False), (lambda c: dmath.power(D(10), D(-30000), ctx=c), False),
	]
	bad = []
	for index, (call, inexact) in enumerate(cases):
		ctx = Context(prec=28)
		call(ctx)
		if bool(ctx.flags[Inexact]) != inexact:
			bad.append(index)
	assert not bad, bad


def test_directed_negative():
	"""Odd results: (−y)^x for an odd integer x and ˣ√(−y) for an odd x, rounded down, are the
	negation of the positive result rounded up."""

	floor	= Context(prec=28, rounding=ROUND_FLOOR)
	ceiling	= Context(prec=28, rounding=ROUND_CEILING)
	rng		= random.Random(f"{SEED}-negative")
	bad		= []
	for _ in range(60):
		y		= random_decimal(rng, -5, 5)
		odd		= D(rng.choice((3, 5, 7, -3, -5, 9)))
		pairs	= [(dmath.power, odd), (dmath.root, odd)]
		for function, x in pairs:
			down	= function(y.copy_negate(), x, ctx=floor)
			up		= function(y, x, ctx=ceiling)
			if down != up.copy_negate():
				bad.append((function.__name__, str(y), str(x), str(down), str(up)))
	assert not bad, bad[:3]


def test_extreme_precisions():
	"""1 to 3 digits, and 100, against the reference in every rounding mode."""

	bad = []
	for name in ('exp', 'ln', 'log10', 'power', 'root'):
		for args in sweep_cases(name, 10):
			bad += against_reference(name, args, precs=(1, 2, 3, 100))
	assert not bad, (len(bad), bad[:3])


def test_monotonic():
	"""Correct rounding keeps monotonicity: f(x) and f(next x) never go the wrong way. All five
	functions increase with x here (yˣ for y > 1 with a positive x, ˣ√y for a positive x)."""

	rng		= random.Random(f"{SEED}-monotonic")
	ctx		= Context(prec=28)
	ranges	= [
		('exp', lambda x: dmath.exp(x, ctx=ctx), -50.0, 50.0), ('ln', lambda x: dmath.ln(x, ctx=ctx), 0.01, 100.0),
		('log10', lambda x: dmath.log10(x, ctx=ctx), 0.01, 100.0),
		('power', lambda x: dmath.power(x, D('2.5'), ctx=ctx), 0.01, 100.0),
		('root', lambda x: dmath.root(x, D(3), ctx=ctx), 0.01, 100.0),
	]
	bad = []
	for name, function, low, high in ranges:
		for _ in range(200):
			x		= ctx.create_decimal(repr(rng.uniform(low, high)))
			after	= ctx.next_plus(x)
			if function(after) < function(x):
				bad.append((name, str(x)))
	assert not bad, bad[:3]


def test_argument_types():
	"""Decimal and int arguments work (int exactly); float, str and None raise TypeError."""

	ctx = Context(prec=28)
	assert dmath.exp(1, ctx=ctx) == dmath.exp(D(1), ctx=ctx)
	assert dmath.power(2, 10, ctx=ctx) == D(1024)
	assert dmath.root(-8, 3, ctx=ctx) == D(-2)
	calls = [lambda a: dmath.exp(a, ctx=ctx), lambda a: dmath.ln(a, ctx=ctx), lambda a: dmath.log10(a, ctx=ctx),
			 lambda a: dmath.power(D(2), a, ctx=ctx), lambda a: dmath.root(a, D(3), ctx=ctx)]
	bad = []
	for index, call in enumerate(calls):
		for bad_arg in (1.0, '1', None):
			if not raises(lambda: call(bad_arg), TypeError):
				bad.append((index, bad_arg))
	assert not bad, bad


def test_extreme_arguments():
	"""Arguments near the exponent limits: right results, and fast (no computation at the
	precision of the argument's decimals, a million digits for 1E-999999)."""

	ctx		= Context(prec=28)
	cases	= [
		(lambda: dmath.exp(D('1E-999999'), ctx=ctx), D(1)), (lambda: dmath.exp(D('-1E-999999'), ctx=ctx), D(1)),
		(lambda: dmath.log10(D('1E999999'), ctx=ctx), D(999999)), (lambda: dmath.log10(D('1E-999999'), ctx=ctx), D(-999999)),
		(lambda: dmath.ln(D('1E999999'), ctx=ctx), ctx.plus(reference('ln', (D('1E999999'),)))),
		(lambda: dmath.ln(D('1E-1000026'), ctx=ctx), ctx.plus(reference('ln', (D('1E-1000026'),)))),
		(lambda: dmath.root(D('1E999999'), D(999999), ctx=ctx), D(10)),
	]
	bad		= []
	slow	= []
	for index, (call, want) in enumerate(cases):
		start	= perf_counter()
		got		= call()
		elapsed	= perf_counter() - start
		if got != want:
			bad.append((index, str(want), str(got)))
		if elapsed > 0.02:
			slow.append((index, f"{elapsed * 1000:.0f} ms"))
	assert not bad, bad
	assert not slow, slow


def test_speed():
	"""Average time per call at 28 digits: below 1 ms."""

	ctx	= Context(prec=28)
	rng	= random.Random(SEED)
	xs	= [random_decimal(rng, -2, 2) for _ in range(100)]
	calls = {
		'exp':		lambda: [dmath.exp(x, ctx=ctx) for x in xs],
		'ln':		lambda: [dmath.ln(x, ctx=ctx) for x in xs],
		'log10':	lambda: [dmath.log10(x, ctx=ctx) for x in xs],
		'power':	lambda: [dmath.power(x, D('2.5'), ctx=ctx) for x in xs],
		'root':		lambda: [dmath.root(x, D(3), ctx=ctx) for x in xs],
	}
	slow = {}
	for name, call in calls.items():
		call()
		start	= perf_counter()
		call()
		per_ms	= (perf_counter() - start) / len(xs) * 1000
		print(f"      {name:5} {per_ms:.3f} ms")
		if per_ms >= 1:
			slow[name] = per_ms
	assert not slow, slow


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
