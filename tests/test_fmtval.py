"""Tests for FmtVal, the number formatter of trpn.calculator.

Runs with pytest, or directly:

	python tests\test_fmtval.py

Each test_* function uses plain asserts. The tests compare what the stack pane displays: the
formatted value, or '#' * width when nothing fits. The random sweep checks the display rules on
many values instead of comparing to fixed outputs, against references written independently of
FmtVal with Decimal's own formatting.
"""

import random
import sys
from decimal import Decimal as D, Context, ROUND_HALF_UP, InvalidOperation, getcontext, setcontext
from decimal import Inexact, Rounded, Underflow, Subnormal, Clamped, Overflow, DivisionByZero

from trpn.calculator import FmtVal

STGSIG		= 28			# storage precision, as in the calculator: Decimal's default precision too
SWEEP_SIZE	= 1500			# random values in the sweep
SWEEP_SEED	= 1
SIGS		= (1, 2, 3, 5, 12, 20)
WIDTHS		= range(1, 31)

FMTVAL		= FmtVal(D(0), 20, 30)	# one FmtVal object, reused through run() as in the app


# --- FmtVal access ---------------------------------------------------------------------------

def display(v, sig, w):
	"""What the stack pane shows for v."""

	return FMTVAL.run(v, sig, w)


def fmtval_fixed(dec):
	"""FmtVal's fixed_str works on its register."""

	FMTVAL.dec_r = dec
	FMTVAL.fixed_str()
	return FMTVAL.fix_r


def fmtval_sci(dec):
	"""FmtVal's sci_str works on its register."""

	FMTVAL.dec_r = dec
	FMTVAL.sci_str()
	return FMTVAL.sci_r


# --- references, independent of FmtVal -------------------------------------------------------

def ref_fixed(d):
	"""Fixed notation of a normalized Decimal, without leading zero: Decimal's 'f' format, 0.5 -> .5."""

	text	= format(d, 'f')
	sign	= '-' if text.startswith('-') else ''
	body	= text.lstrip('-')
	if body.startswith('0.'):
		body = body[1:]
	return sign + body


def ref_sci(d):
	"""Scientific notation of a normalized Decimal: Decimal's 'E' format, without the exponent's '+'."""

	text = format(d, 'E')
	return text.replace('E+', 'E')


# --- helpers ---------------------------------------------------------------------

def sig_digits(s):
	"""Significant digits shown in a formatted number."""

	mantissa = s.split('E')[0]
	return len(mantissa.replace('-', '').replace('.', '').lstrip('0'))


def resolution(s):
	"""Exponent of the last digit shown: .000099 -> -6, 9.88E-5 -> -7, 1E12 -> 12."""

	mantissa, _, exp = s.partition('E')
	decimals = len(mantissa.partition('.')[2])
	return (int(exp) if exp else 0) - decimals


def fixed_allowed(d, sig):
	"""HP48 rule: fixed notation takes at most sig digit positions."""

	e			= d.adjusted()
	n_digits	= len(d.as_tuple().digits)
	positions	= e + 1 if e >= 0 else n_digits - e - 1
	return positions <= sig


def check(cases):
	"""cases: (val, sig, width, expected). Returns the mismatches."""

	bad = []
	for v, sig, w, want in cases:
		got = display(v, sig, w)
		if got != want:
			bad.append((str(v), sig, w, want, got))
	return bad


# --- expected outputs ---------------------------------------------------------------

def test_hp48():
	"""Values checked on an HP48 emulator in STD mode (sig 12), without its 1.E dot."""

	cases = [
		('0.000123', '.000123'), ('9.87654321E-5', '9.87654321E-5'), ('1E-12', '.000000000001'),
		('1.5E-12', '1.5E-12'), ('1.23E-10', '.000000000123'), ('1.234E-10', '1.234E-10'),
		('1E11', '100000000000'), ('1E12', '1E12'), ('1E100', '1E100'), ('12345678901.5', '12345678901.5'),
		('1.000000000005', '1.00000000001'), ('-1.000000000005', '-1.00000000001'),
		('999999999999.5', '1E12'), ('123456789012.5', '123456789013'), ('-.5', '-.5'), ('55', '55'),
	]
	cases = [(D(v), 12, 30, want) for v, want in cases]
	cases += [(D(2) / 3, 12, 30, '.666666666667'), (D(1) / 3, 12, 30, '.333333333333'),
			  (D(2) ** 200, 12, 30, '1.60693804426E60')]
	bad = check(cases)
	assert not bad, bad


def test_stack_b():
	"""Stack with (1/3) * 3, sig 20; widths are the value field (pane width minus '9: ')."""

	stack = [D(55), D(2) / 3, (D(1) / 3) * 3, D(2) ** 200, D('1E15'), D('9.87654321E-5'), D('-.5'),
			 D('1.5E-25'), D('.000123'), D(0)]
	expected = {
		37: ['55', '.66666666666666666667', '1', '1.6069380442589902755E60', '1000000000000000',
			 '.0000987654321', '-.5', '1.5E-25', '.000123', '0'],
		17: ['55', '.6666666666666667', '1', '1.606938044259E60', '1000000000000000', '.0000987654321',
			 '-.5', '1.5E-25', '.000123', '0'],
		7:  ['55', '.666667', '1', '1.61E60', '1E15', '9.88E-5', '-.5', '1.5E-25', '.000123', '0'],
		5:  ['55', '.6667', '1', '2E60', '1E15', '.0001', '-.5', '2E-25', '.0001', '0'],
	}
	for w, want in expected.items():
		got = [display(v, 20, w) for v in stack]
		assert got == want, (w, got)


def test_stack_a():
	"""The ini() stack plus 0.1 + 0.2, sig 20."""

	stack = [D('-123.45'), D(124567), D('312.2645'), D('-5.465789'), D('16.4'), D(1000000), D('0.1') + D('0.2')]
	expected = {
		20: ['-123.45', '124567', '312.2645', '-5.465789', '16.4', '1000000', '.3'],
		9:  ['-123.45', '124567', '312.2645', '-5.465789', '16.4', '1000000', '.3'],
		5:  ['-123', '1.2E5', '312.3', '-5.47', '16.4', '1E6', '.3'],
	}
	for w, want in expected.items():
		got = [display(v, 20, w) for v in stack]
		assert got == want, (w, got)


def test_calculations():
	"""Decimal arithmetic results at sig 12 and 20, 40-column value field."""

	cases = [
		(D('0.1') + D('0.2'), '.3', '.3'), (1 - D('0.9'), '.1', '.1'), (D('1.1') * 3, '3.3', '3.3'),
		(D('0.1') * 3, '.3', '.3'), (D(2) / 3, '.666666666667', '.66666666666666666667'),
		((D(1) / 3) * 3, '1', '1'), (D(2) ** 200, '1.60693804426E60', '1.6069380442589902755E60'),
	]
	bad = check([(v, 12, 40, w12) for v, w12, _ in cases] + [(v, 20, 40, w20) for v, _, w20 in cases])
	assert not bad, bad


def test_worked_examples():
	"""Examples from the design discussion: double rounding, resolution, narrow widths."""

	cases = [
		(D('9.87654321E-5'), 20, 7, '9.88E-5'),				# sci keeps more digits than .000099
		(D('0.005600489413198'), 5, 8, '.0056'),			# no double rounding (not 5.601E-3)
		(D('0.000771796624004959399687'), 12, 15, '.000771796624'),
		(D('1E-8'), 20, 5, '1E-8'),							# fixed allowed but too wide
		(D('.000123'), 20, 17, '.000123'),
		(D('1.5E-25'), 20, 30, '1.5E-25'),					# 26 positions: scientific
		(D('-0.006634148396030'), 5, 6, '-.0066'),
		(D('0.0123456789012345678911'), 20, 22, '.01234567890123456789'),	# decimals capped by sig
		(D(2) / 3, 20, 1, '1'),								# cand2 (7E-1) too wide: integer rounding
		(D('-0.0000799999999'), 5, 6, '-8E-5'),				# resolution: not -.0001
		(D('0.000537654433'), 3, 4, '5E-4'),				# resolution: not .001
		(D('0.00045678'), 5, 6, '.00046'),					# same resolution: fixed wins the tie
		(D('999.6'), 20, 3, '1E3'),							# candidate 1 carries to 1000, written 1E3
		(D('-0.5'), 20, 1, '#'),							# nothing fits
		(D('9.996'), 20, 1, '#'),							# carry to 10: neither 10 nor 1E1 fits
	]
	bad = check(cases)
	assert not bad, bad


def test_zeros():
	"""0, -0 and zeros with an exponent always show 0."""

	got = {display(z, s, w) for z in (D(0), D('-0'), D('0.000'), D('-0.0E5')) for s in (1, 12, 20) for w in (1, 5, 40)}
	assert got == {'0'}, got


def test_range_limits():
	"""Values next to the exponent limits. Rounding to fewer digits can carry a value past the
	stack's ceiling (9.6E999999 at 1 digit is 1E1000000): the display writes that text, it once
	crashed with decimal.Overflow. The tiniest values display too (display rounding once made
	1E-1000026 a 0)."""

	cases = [
		(D('9.6E999999'), 20, 10, '9.6E999999'), (D('9.6E999999'), 20, 9, '1E1000000'),
		(D('9.6E999999'), 20, 8, '########'), (D('9.6E999999'), 20, 6, '######'),
		(D('9.99999E999999'), 20, 14, '9.99999E999999'), (D('9.99999E999999'), 20, 12, '1E1000000'),
		(D('9.9999999999999999999E999999'), 20, 30, '9.9999999999999999999E999999'),
		(D('9.99999999999999999999E999999'), 20, 30, '1E1000000'),				# 21 nines: 20 shown
		(D('-9.6E999999'), 20, 10, '-1E1000000'), (D('1.5E-999999'), 20, 9, '2E-999999'),
		(D('1E-1000026'), 20, 30, '1E-1000026'), (D('1.234567E-1000020'), 20, 30, '1.234567E-1000020'),
	]
	bad = check(cases)
	assert not bad, bad


def test_global_context_independence():
	"""Every rounding runs in an explicit context: a hostile global context (1 digit, a tiny
	exponent range, every signal trapped) changes nothing."""

	values	= [D('-123.45'), D('9.87654321E-5'), D('0.000537654433'), D('999.6'), D('9.6E999999'), D(2) / 3]
	cases	= [(v, sig, w) for v in values for sig in (3, 20) for w in (1, 5, 9, 30)]
	want	= [display(v, sig, w) for v, sig, w in cases]
	saved	= getcontext()
	try:
		setcontext(Context(prec=1, Emin=-3, Emax=3, traps=[Inexact, Rounded, Underflow, Subnormal, Clamped,
															 Overflow, InvalidOperation, DivisionByZero]))
		got = [display(v, sig, w) for v, sig, w in cases]
	finally:
		setcontext(saved)
	bad = [(str(v), sig, w, a, b) for (v, sig, w), a, b in zip(cases, want, got) if a != b]
	assert not bad, bad


def test_helpers():
	"""FmtVal's fixed_str and sci_str on normalized values."""

	cases = [
		(D('-123.45'), '-123.45', '-1.2345E2'), (D('0.000123'), '.000123', '1.23E-4'),
		(D('1E+6'), '1000000', '1E6'), (D('-0.5'), '-.5', '-5E-1'), (D(55), '55', '5.5E1'),
	]
	bad = []
	for v, f, s in cases:
		got = (fmtval_fixed(v), fmtval_sci(v))
		if got != (f, s):
			bad.append((str(v), got))
	assert not bad, bad


# --- display rules on random values -----------------------------------------------------

def sweep_values():
	"""Random Decimals: 1 to 28 digits, exponents -35..35, with carry-prone x.999... and
	halfway-trap ...4999... values."""

	rng		= random.Random(SWEEP_SEED)
	values	= []
	for _ in range(SWEEP_SIZE):
		nd		= rng.randint(1, 28)
		digits	= str(rng.randint(1, 9)) + ''.join(str(rng.randint(0, 9)) for _ in range(nd - 1))
		r		= rng.random()
		if r < 0.2:
			digits = digits[0] + '9' * (nd - 1)
		elif r < 0.4:
			digits = digits[:rng.randint(1, nd)] + '4' + '9' * rng.randint(1, 5) + digits[:3]
		sign = '-' if rng.random() < 0.3 else ''
		values.append(D(f"{sign}{digits}E{rng.randint(-35, 35)}"))
	return values


def correct_forms(v, sig):
	"""Every correctly rounded display of v allowed by the sig rule: fixed with any number of
	decimals, scientific with any number of digits. Returns (text, resolution) pairs.
	Built with ref_fixed / ref_sci, independent of FmtVal."""

	forms	= []
	ctx		= Context(prec=60, rounding=ROUND_HALF_UP)		# room for every decimal tried

	for dp in range(0, 45):
		try:
			r = v.quantize(D(10) ** -dp, context=ctx).normalize(ctx)
		except InvalidOperation:							# more digits than ctx allows
			break
		if r == 0 or len(r.as_tuple().digits) > sig or not fixed_allowed(r, sig):
			continue
		forms.append((ref_fixed(r), -dp))
	for k in range(1, sig + 1):
		r = v.normalize(Context(prec=k, rounding=ROUND_HALF_UP))
		s = ref_sci(r)
		forms.append((s, resolution(s)))
	return forms


def test_sweep():
	"""On random values: never wider than the width, at most sig digits, correctly rounded,
	scientific only when no fixed form that fits is as fine, and #### only when no correctly
	rounded form fits."""

	problems	= {'wider than the width': [], 'more than sig digits': [], 'not correctly rounded': [],
				   'sci although fixed as fine': [], '#### although a form fits': []}
	for v in sweep_values():
		for sig in SIGS:
			forms = correct_forms(v, sig)
			for w in WIDTHS:
				out		= display(v, sig, w)
				fitting	= [(s, res) for s, res in forms if len(s) <= w]
				if len(out) > w:
					problems['wider than the width'].append((str(v), sig, w, out))
					continue
				if out == '#' * w:
					if fitting:
						problems['#### although a form fits'].append((str(v), sig, w, fitting[0][0]))
					continue
				if sig_digits(out) > sig:
					problems['more than sig digits'].append((str(v), sig, w, out))
				err = abs(D(out) - v)
				if err > D(10) ** resolution(out) / 2:
					problems['not correctly rounded'].append((str(v), sig, w, out))
				if 'E' in out:
					fixed_fits = [res for s, res in fitting if 'E' not in s]
					if fixed_fits and min(fixed_fits) <= resolution(out):
						problems['sci although fixed as fine'].append((str(v), sig, w, out))
	report = {k: (len(p), p[:3]) for k, p in problems.items() if p}
	assert not report, report


# --- runner ---------------------------------------------------------------------------------

if __name__ == '__main__':
	getcontext().prec = STGSIG
	tests	=[(name, fn) for name, fn in globals().items() if name.startswith('test_') and callable(fn)]
	failed	= 0
	for name, fn in tests:
		try:
			fn()
			print(f"PASS  {name}")
		except AssertionError as err:
			failed += 1
			print(f"FAIL  {name}: {err}")
	print(f"\n{len(tests) - failed}/{len(tests)} passed")
	sys.exit(1 if failed else 0)
