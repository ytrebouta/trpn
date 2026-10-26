"""Exponentials, logarithms and powers on Decimals, correctly rounded: exp, ln, log10, power (yˣ)
and root (ˣ√y).

Each result is the exact value rounded once to the precision and rounding mode of the context (the
current one by default). Decimal's own exp(), ln() and log10() are correctly rounded too, but always
half-even; these functions follow the context's rounding mode, as + − × ÷ do.

How: Ziv's strategy. A kernel computes the value at a working precision wp = prec + guard digits,
together with a bound on its error. If both ends of the interval value ± error round to the same
result, that result is the correctly rounded value. Otherwise the guard grows and the kernel runs
again. Exact results (2^10, 4^0.5, ³√8, ...) are returned before the loop: on a rounding boundary,
the loop could never decide.

The global decimal context is never modified: all arithmetic runs in local contexts.

Note for use as a library: in the directed rounding modes (ROUND_UP, ROUND_DOWN, ROUND_FLOOR,
ROUND_CEILING, ROUND_05UP), a result within about 1E-4100 of 1 can't be decided, and raises
InvalidOperation. The nearest modes, which trpn uses, aren't affected:

	exp(Decimal('1E-5000'), ctx=Context(prec=28, rounding=ROUND_HALF_UP))	# 1
	exp(Decimal('1E-5000'), ctx=Context(prec=28, rounding=ROUND_UP))		# raises InvalidOperation
"""

from decimal import Decimal, Context, localcontext, getcontext, InvalidOperation
from decimal import ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN, MIN_EMIN, MAX_EMAX
from fractions import Fraction

GUARD		= 8						# guard digits of the first try
MAX_TRIES	= 10					# tries before giving up (reached only by the near-one limit, in the directed modes)

# Every operation on Decimals runs in an explicit context: the global one may have any precision,
# rounding or traps. Even abs(), +x and -x round to the global context: arguments go through
# copy_abs() and copy_negate(), which are exact.

# Internal contexts have an unlimited exponent range: intermediate values neither overflow nor
# underflow. Only the final rounding uses the caller's limits.

_WIDE		= {'Emin': MIN_EMIN, 'Emax': MAX_EMAX}


# --- Ziv loop ---------------------------------------------------------------------------------

def _decided(y, err, wp, ctx):
	"""True when every value in y ± err rounds to the same result in ctx."""

	outward	= wp + 5
	low		= Context(**_WIDE, prec=outward, rounding=ROUND_FLOOR).subtract(y, err)		# rounded outward: the
	high	= Context(**_WIDE, prec=outward, rounding=ROUND_CEILING).add(y, err)			# interval only grows

	# The caller's limits, but no traps: an overflow or underflow here is only compared, the caller's
	# own context decides afterwards whether it raises

	probe	= Context(prec=ctx.prec, rounding=ctx.rounding, Emin=ctx.Emin, Emax=ctx.Emax, traps=[])

	# compare_total, not ==: −0 and +0 are equal numbers but different results (a tiny positive
	# value rounded to zero must not come out as −0)

	return probe.plus(low).compare_total(probe.plus(high)) == 0


def _ziv(approx, args, ctx):
	"""Runs approx(wp, *args) -> (value, error bound, digits the kernel lost) with more and
	more guard digits until the result is decided, then returns it rounded in ctx."""

	guard = GUARD

	for _ in range(MAX_TRIES):
		wp				= ctx.prec + guard
		y, err, lost	= approx(wp, *args)

		if _decided(y, err, wp, ctx):
			return ctx.plus(y)

		guard += max(guard, lost)							# lost: digits the kernel lost, on top of the guard

	raise InvalidOperation('could not round the result correctly')


# --- argument checks --------------------------------------------------------------------------

def _as_decimal(x, name):
	"""Decimal arguments as they are, int ones converted exactly; anything else raises TypeError
	(a float would bring its binary error along)."""

	if isinstance(x, Decimal):
		return x

	if isinstance(x, int):
		return Decimal(x)

	raise TypeError(f"{name}: argument must be a Decimal or an int, not {type(x).__name__}")


# --- exponentials, logarithms, powers ---------------------------------------------------------

# e^t beyond a context's exponent range is settled before computing it: 2.31 > ln 10 = 2.3026, so
# t > 2.31·(Emax + 2) means e^t > 10^(Emax + 2), and t < 2.31·(Etiny − 2) means e^t < 10^(Etiny − 2).

_LN10_ABOVE		= Decimal('2.31')
_EXACT_DIGITS	= 30					# exactness candidates are computed to prec + 30 digits
_EXACT_BITS		= 66439					# bits allowed in the integer powers of the exactness check (20000 digits)


def _coefficient(d):
	"""(m, e) with d = m × 10^e and m an integer not divisible by 10, for a finite nonzero d.
	Exact, without context."""

	sign, digits, exponent	= d.as_tuple()
	m						= int(''.join(map(str, digits)))
	e						= exponent

	while m % 10 == 0:
		m	//= 10
		e	+= 1

	return m, e


def _beyond_range(t, ctx):
	"""A stand-in for e^t when e^t is certainly beyond ctx's exponent range, else None. ctx.plus()
	rounds the stand-in exactly as it would round e^t: an overflow above; 0 or the smallest
	subnormal below, depending on the rounding mode."""

	small	= Context(**_WIDE, prec=12)
	high	= small.multiply(_LN10_ABOVE, Decimal(ctx.Emax + 2))
	low		= small.multiply(_LN10_ABOVE, Decimal(ctx.Etiny() - 2))

	if t > high:
		return Decimal(1).scaleb(ctx.Emax + 2, small)

	if t < low:
		return Decimal(1).scaleb(ctx.Etiny() - 2, small)

	return None


def _exp_approx(wp, x):
	"""e^x at wp digits. Decimal's exp is correctly rounded: off by half an ulp at most."""

	with localcontext(Context(**_WIDE, prec=wp)):
		eps	= Decimal(1).scaleb(1 - wp)
		y	= x.exp()
		err	= y * eps											# y > 0; one ulp, twice the need

	return y, err, 0


def _ln_approx(wp, x):
	"""ln x at wp digits, x > 0, correctly rounded by Decimal: half an ulp at most."""

	with localcontext(Context(**_WIDE, prec=wp)):
		eps	= Decimal(1).scaleb(1 - wp)
		y	= x.ln()
		err	= y.copy_abs() * eps

	return y, err, 0


def _log10_approx(wp, x):
	"""log10 x at wp digits, x > 0, correctly rounded by Decimal: half an ulp at most."""

	with localcontext(Context(**_WIDE, prec=wp)):
		eps	= Decimal(1).scaleb(1 - wp)
		y	= x.log10()
		err	= y.copy_abs() * eps

	return y, err, 0


def _pow_exponent(wp, base, x, invert):
	"""t = x·ln(base), or ln(base)/x when invert (a root), at wp digits: base^x or base^(1/x) is e^t.
	ln is off by half an ulp, the product or quotient by half an ulp more: t is off by |t|·eps."""

	with localcontext(Context(**_WIDE, prec=wp)):
		log = base.ln()
		if invert:
			t = log / x
		else:
			t = x * log

	return t


def _pow_value(wp, base, x, invert):
	"""(z, t, rel): z = e^t, the power or root at wp digits, t its exponent (_pow_exponent), rel a
	bound on z's relative error. t's error δ = |t|·eps moves e^t by a factor e^δ, and e^δ − 1 is
	below 1.01·δ while δ < 0.01; exp adds half an ulp. A larger δ gives an infinite bound."""

	t = _pow_exponent(wp, base, x, invert)

	with localcontext(Context(**_WIDE, prec=wp)):
		eps		= Decimal(1).scaleb(1 - wp)
		z		= t.exp()
		delta	= t.copy_abs() * eps
		if delta < Decimal('0.01'):
			rel = delta * Decimal('1.01') + eps
		else:
			rel = Decimal('Infinity')							# retry with more digits

	return z, t, rel


def _power_approx(wp, base, x, invert, sign):
	"""The power or root for the Ziv loop: (value with its sign, error bound, digits lost). t's
	integer digits are lost to the exponential: they go on top of the guard."""

	z, t, rel = _pow_value(wp, base, x, invert)

	with localcontext(Context(**_WIDE, prec=wp)):
		err = z * rel

	if sign < 0:
		z = z.copy_negate()

	lost = max(0, t.adjusted() + 1)
	return z, err, lost


def _exact_power(base, x, invert, ctx):
	"""base^x (base^(1/x) when invert), base > 0, when that result is exact with at most
	ctx.prec + 1 digits, else None. Such a result can sit on a rounding boundary, where the Ziv
	loop could never decide: 4^0.5 = 2, 4^2.5 = 32, ³√8 = 2, ³√1E300 = 1E100.

	A candidate c is computed to ctx.prec + _EXACT_DIGITS digits, then checked exactly in integers:
	with base^(num/den), c is exact when c^den = base^num."""

	exponent = Fraction(x)
	if invert:
		exponent = 1 / exponent
	num = exponent.numerator
	den = exponent.denominator

	digits	= ctx.prec + _EXACT_DIGITS
	wp		= digits + 10
	t		= _pow_exponent(12, base, x, invert)
	wp		+= max(0, t.adjusted() + 1)							# t's integer digits are lost to exp

	z, t, rel = _pow_value(wp, base, x, invert)
	if rel.is_infinite():
		return None

	c = Context(**_WIDE, prec=digits, rounding=ROUND_HALF_EVEN).plus(z)
	c_m, c_e = _coefficient(c)
	if len(str(c_m)) > ctx.prec + 1:							# longer: not on a boundary, the loop decides
		return None

	# The size of c^den and base^|num| in bits, in integers only: den and num can be far beyond a
	# float (x = 1E-999999). A power of ten has coefficient 1, whose powers cost nothing.

	b_m, b_e	= _coefficient(base)
	bits		= den * (c_m.bit_length() - 1) + abs(num) * (b_m.bit_length() - 1)
	if bits > _EXACT_BITS:										# too costly to check
		return None

	# The exact value in the form an exact operation gives it: 1024, not 1024.000000000000000000000000;
	# an integer as an integer while it fits the precision (100, as 10 × 10 gives), else 1E+100

	digits_c	= tuple(int(digit) for digit in str(c_m))
	int_digits	= len(digits_c) + c_e
	if c_e > 0 and int_digits <= ctx.prec:
		shortest = Decimal(c_m * 10 ** c_e)
	else:
		shortest = Decimal((0, digits_c, c_e))

	# c^den = base^num, both written m × 10^e with m not divisible by 10

	if num > 0:
		left_m	= c_m ** den
		right_m	= b_m ** num
		left_e	= c_e * den
		right_e	= b_e * num
		if left_m == right_m and left_e == right_e:
			return shortest
		return None

	# num < 0: c^den × base^|num| = 1, so the product of the coefficients is a power of ten

	product		= (c_m ** den) * (b_m ** -num)
	power_ten	= -(c_e * den + b_e * -num)
	beyond		= 3 * power_ten >= product.bit_length()				# 10^k > 2^(3k): past the product already
	if power_ten >= 0 and not beyond and product == 10 ** power_ten:
		return shortest
	return None


def _pow_common(base, x, invert, sign, ctx):
	"""power and root once their special cases are settled: base > 0, sign the result's sign."""

	if base == 1:
		return ctx.plus(Decimal(sign))

	t		= _pow_exponent(20, base, x, invert)
	beyond	= _beyond_range(t, ctx)									# before e^t is computed at all
	if beyond is not None:
		if sign < 0:
			beyond = beyond.copy_negate()
		return ctx.plus(beyond)

	exact = _exact_power(base, x, invert, ctx)
	if exact is not None:
		if sign < 0:
			exact = exact.copy_negate()
		return ctx.plus(exact)

	return _ziv(_power_approx, (base, x, invert, sign), ctx)


def exp(x, ctx=None):
	"""e to the power x, correctly rounded in ctx. exp(−Infinity) is 0, exp(Infinity) is Infinity."""

	ctx = ctx if ctx is not None else getcontext()
	x = _as_decimal(x, 'exp')

	if x.is_nan():
		return ctx.plus(x)

	if x.is_infinite():
		if x < 0:
			return ctx.plus(Decimal(0))
		return ctx.plus(x)

	if x == 0:
		return ctx.plus(Decimal(1))

	beyond = _beyond_range(x, ctx)
	if beyond is not None:
		return ctx.plus(beyond)

	return _ziv(_exp_approx, (x,), ctx)


def ln(x, ctx=None):
	"""Natural logarithm of x, correctly rounded in ctx. ln 0 is −Infinity; a negative x raises
	InvalidOperation (the result would be complex)."""

	ctx = ctx if ctx is not None else getcontext()
	x = _as_decimal(x, 'ln')

	if x.is_nan():
		return ctx.plus(x)

	if x < 0:
		raise InvalidOperation('ln: negative argument')

	if x == 0:
		return ctx.plus(Decimal('-Infinity'))

	if x.is_infinite():
		return ctx.plus(x)

	if x == 1:
		return ctx.plus(Decimal(0))

	return _ziv(_ln_approx, (x,), ctx)


def log10(x, ctx=None):
	"""Base-10 logarithm of x, correctly rounded in ctx; exact for the powers of ten. log10 0 is
	−Infinity; a negative x raises InvalidOperation."""

	ctx = ctx if ctx is not None else getcontext()
	x = _as_decimal(x, 'log10')

	if x.is_nan():
		return ctx.plus(x)

	if x < 0:
		raise InvalidOperation('log10: negative argument')

	if x == 0:
		return ctx.plus(Decimal('-Infinity'))

	if x.is_infinite():
		return ctx.plus(x)

	m, e = _coefficient(x)
	if m == 1:													# x = 10^e
		return ctx.plus(Decimal(e))

	return _ziv(_log10_approx, (x,), ctx)


def power(y, x, ctx=None):
	"""y to the power x, correctly rounded in ctx. 0^0 is 1; 0 to a negative power is Infinity; a
	negative y needs an integer x, else InvalidOperation (the result would be complex)."""

	ctx = ctx if ctx is not None else getcontext()
	y = _as_decimal(y, 'power')
	x = _as_decimal(x, 'power')

	if y.is_nan() or x.is_nan():
		return ctx.plus(y if y.is_nan() else x)

	if y.is_infinite() or x.is_infinite():
		raise InvalidOperation('power: infinite argument')

	if x == 0:
		return ctx.plus(Decimal(1))								# 0^0 included

	if y == 0:
		if x > 0:
			return ctx.plus(Decimal(0))
		return ctx.plus(Decimal('Infinity'))

	sign = 1
	if y < 0:
		exponent = Fraction(x)
		if exponent.denominator != 1:
			raise InvalidOperation('power: complex result')
		if exponent.numerator % 2 == 1:
			sign = -1

	return _pow_common(y.copy_abs(), x, False, sign, ctx)


def root(y, x, ctx=None):
	"""The x-th root of y, y^(1/x), correctly rounded in ctx. x = 0 raises InvalidOperation; the
	root of 0 is 0 for x > 0 and Infinity for x < 0; a negative y needs an odd integer x, else
	InvalidOperation (the result would be complex)."""

	ctx = ctx if ctx is not None else getcontext()
	y = _as_decimal(y, 'root')
	x = _as_decimal(x, 'root')

	if y.is_nan() or x.is_nan():
		return ctx.plus(y if y.is_nan() else x)

	if y.is_infinite() or x.is_infinite():
		raise InvalidOperation('root: infinite argument')

	if x == 0:
		raise InvalidOperation('root: zeroth root')

	if y == 0:
		if x > 0:
			return ctx.plus(Decimal(0))
		return ctx.plus(Decimal('Infinity'))

	sign = 1
	if y < 0:
		index = Fraction(x)
		if index.denominator != 1 or index.numerator % 2 == 0:
			raise InvalidOperation('root: complex result')
		sign = -1

	return _pow_common(y.copy_abs(), x, True, sign, ctx)
