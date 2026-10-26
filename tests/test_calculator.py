"""Tests for RpnCalculator: keys, stack, operations, modes and the panes' drawing.

Runs with pytest, or directly:

	python tests\test_calculator.py

Each test builds a calculator without a terminal: Maupertuis is built to a known size and the
terminal is replaced by a stand-in whose move_xy writes a readable marker, so the panes can be
read back as rows of text. Keys are blessed Keystrokes sent through keyprocess(), followed by
col_update(), as run() does after each key.
"""

import re
import sys
from decimal import Decimal as D, Context
from time import perf_counter

from blessed.keyboard import Keystroke

from trpn.calculator import RpnCalculator, FmtVal

SPECIAL = {
	'ENTER':	Keystroke('\r', name='KEY_ENTER'),
	'BS':		Keystroke('\x08', name='KEY_BACKSPACE'),
	'DEL':		Keystroke('\x1b[3~', name='KEY_DELETE'),
	'RIGHT':	Keystroke('\x1b[C', name='KEY_RIGHT'),
	'ESC':		Keystroke('\x1b', name='KEY_ESCAPE'),
}


class StubTerm:
	"""move_xy as a readable marker: the drawn text can be cut back into rows."""

	def move_xy(self, x, y):
		return f"\x00{x},{y}\x00"


def stack16():
	"""The 16-level test stack: every kind of display case."""

	stg = Context(prec=28)
	return [
		D('0'), D('55'), D('-123.45'), stg.divide(D(2), D(3)), stg.multiply(stg.divide(D(1), D(3)), D(3)),
		stg.divide(D(355), D(113)), D('9.87654321E-5'), D('-0.0000799999999'), D('1000000'), D('-123456789'),
		D('12345678901234567890123'), stg.power(D(2), 200), D('1.5E-25'), D('-.5'), D('999.6'), D('124567.89'),
	]


def calc_with(stack=(), field='', width=80, height=25):
	"""A calculator with this stack and field, its panes built for width × height (the stack pane
	is height − 5 rows: the error line, the bar, the input field, the mode and keys lines take the
	rest), as run() starts it: panes built, column set, then a first frame drawn."""

	calc = RpnCalculator()
	calc.ini()
	calc.term = StubTerm()
	calc.data['stack'] = [D(v) if not isinstance(v, D) else v for v in stack]
	calc.data['in_field'] = field
	calc.data['inf_open'] = field != ''						# a field given is an entry under way
	calc.mp.build(width, height)
	calc.col_update()
	calc.sts_update()
	calc.mp.draw()											# the first frame: no full redraw nor dirty pane left
	return calc


def press(calc, keys):
	"""Sends the keys (characters, or names from SPECIAL) as run() does: the error cleared, the
	key, then col_update and sts_update. Returns the error codes raised."""

	errors = []
	for k in keys:
		calc.data['err'] = None
		calc.data['key'] = SPECIAL.get(k, Keystroke(k))
		calc.keyprocess()
		calc.col_update()
		calc.sts_update()
		calc.data['key'] = None
		if calc.data['err']:
			errors.append(calc.data['err'])
	return errors


def keys_of(text):
	"""'12↵3+' as a key list: ↵ Enter, ⌫ Backspace, ⌦ Delete, → right arrow, ⎋ Escape."""

	names = {'↵': 'ENTER', '⌫': 'BS', '⌦': 'DEL', '→': 'RIGHT', '⎋': 'ESC'}
	return [names.get(c, c) for c in text]


def stack_of(calc):
	return [str(v) for v in calc.data['stack']]


def rows(calc, pane):
	"""The pane as drawn, one string per row."""

	x0, y0, w, h	= calc.mp.panes[pane]
	out				= calc.draw_fns[pane](x0, y0, w, h)
	found			= {}
	for match in re.finditer(r"\x00(\d+),(\d+)\x00([^\x00]*)", out):
		found[int(match.group(2))] = match.group(3)
	return [found[y] for y in sorted(found)]


def check(cases):
	"""cases: (keys, start stack, start field, expected stack, expected field, expected errors).
	Every case also ends with no mode on: recall and shift are one-shot. Returns the mismatches."""

	bad = []
	for keys, start, field, want_stack, want_field, want_errors in cases:
		calc	= calc_with(start, field)
		errors	= press(calc, keys_of(keys))
		got		= (stack_of(calc), calc.data['in_field'], errors, calc.data['mode'])
		if got != (want_stack, want_field, want_errors, None):
			bad.append((keys, got))
	return bad


# --- entry ------------------------------------------------------------------------------------

def test_entry():
	"""Digits, e (exponent), . (dot) and m (sign) in the input field, with their error codes."""

	cases = [
		('123', [], '', [], '123', []),
		('m1.5em25', [], '', [], '-1.5E-25', []),
		('m', [], '', [], '-', []), ('mm', [], '', [], '', []), ('5m', [], '', [], '-5', []),
		('e', [], '', [], '1E', []), ('me', [], '', [], '-1E', []), ('.e', [], '', [], '1E', []),
		('1ee', [], '', [], '1', []), ('1eme', [], '', [], '1', []),
		('1e5e', [], '', [], '1E5', ['INFEXPDUP']), ('1em5e', [], '', [], '1E-5', ['INFEXPDUP']),
		('1..', [], '', [], '1', []), ('1.5.', [], '', [], '1.5', ['INFDOTDUP']),
		('1e5.', [], '', [], '1E5', ['INFEXPDOT']),
		('1e5m', [], '', [], '1E-5', []), ('1e5mm', [], '', [], '1E5', []),
		('005', [], '', [], '005', []),
		('1⌫', [], '', [], '', []), ('1e⌫2', [], '', [], '12', []),
		('12s⌫', [], '', [], '', []), ('12⌦', [], '', [], '12', []),
	]
	bad = check(cases)
	assert not bad, bad


def test_entry_limits():
	"""28 significant digits at most (leading zeros don't count); the value's exponent within
	±999999, checked on the value, not on the typed digits."""

	cases = [
		('1' * 29, [], '', [], '1' * 28, ['INFDGTMAX']),
		('0.000' + '1' * 29, [], '', [], '0.000' + '1' * 28, ['INFDGTMAX']),
		('15e999999', [], '', [], '15E99999', ['INFEXPMAX']),
		('1e999999', [], '', [], '1E999999', []),
		('0.0000001e1000005', [], '', [], '0.0000001E1000005', []),
		('.01e999999m', [], '', [], '.01E999999', ['INFEXPMAX']),
		('1e999999m', [], '', [], '1E-999999', []),
	]
	bad = check(cases)
	assert not bad, bad


def test_push():
	"""Enter pushes the entry exactly, completing what's unfinished: no mantissa digit is 0, an
	exponent without digit is dropped, a zero is never −0."""

	cases = [
		('123↵', [], '', ['123'], '', []), ('m1.5em25↵', [], '', ['-1.5E-25'], '', []),
		('m↵', [], '', ['0'], '', []), ('.↵', [], '', ['0'], '', []), ('m.↵', [], '', ['0'], '', []),
		('1e↵', [], '', ['1'], '', []), ('1em↵', [], '', ['1'], '', []), ('m1em↵', [], '', ['-1'], '', []),
		('m0↵', [], '', ['0'], '', []), ('m0e5↵', [], '', ['0'], '', []),
		('005↵', [], '', ['5'], '', []), ('5.↵', [], '', ['5'], '', []), ('m.5↵', [], '', ['-0.5'], '', []),
	]
	bad = check(cases)
	assert not bad, bad
	assert not calc_with().data['stack']
	pushed = calc_with()
	press(pushed, keys_of('m0↵'))
	assert not pushed.data['stack'][0].is_signed()


def test_enter_backspace_delete():
	"""With no entry under way, Enter duplicates level 0 and Backspace drops it. During an entry,
	even emptied, Backspace removes the last character and never drops; Enter ends the entry
	(pushing nothing when emptied). Delete does nothing."""

	cases = [
		('7↵↵', [], '', ['7', '7'], '', []), ('↵', [], '', [], '', ['OPRARGMIS']),
		('7↵⌫', [], '', [], '', []), ('⌫', [], '', [], '', ['OPRARGMIS']),
		('78⌫↵', [], '', ['7'], '', []), ('⌦', ['5'], '12', ['5'], '12', []),
		('12⌫⌫⌫⌫', ['5'], '', ['5'], '', []), ('⌫⌫⌫', ['5'], '12', ['5'], '', []),
		('mm⌫', ['5'], '', ['5'], '', []),
		('12⌫⌫↵', ['5'], '', ['5'], '', []), ('12⌫⌫↵⌫', ['5'], '', [], '', []),
		('12⌫⌫↵↵', ['5'], '', ['5', '5'], '', []),
	]
	bad = check(cases)
	assert not bad, bad


def test_stack_full():
	"""100 levels at most: a push or a DUP beyond is refused (PSHSTKFUL), the entry stays."""

	full = [str(i) for i in range(100)]
	cases = [
		('5↵', full, '', full, '5', ['PSHSTKFUL']), ('↵', full, '', full, '', ['PSHSTKFUL']),
		('5+', full, '', full, '5', ['PSHSTKFUL']), ('↵', full[:99], '', full[:99] + ['98'], '', []),
	]
	bad = check(cases)
	assert not bad, bad


def test_swap():
	"""→ swaps levels 0 and 1, after pushing a pending entry."""

	cases = [
		('1↵2↵→', [], '', ['2', '1'], '', []), ('1↵2→', [], '', ['2', '1'], '', []),
		('→→', ['5', '6', '7'], '', ['5', '6', '7'], '', []), ('→', ['5'], '', ['5'], '', ['OPRARGMIS']),
		('9→', [], '', ['9'], '', ['OPRARGMIS']),
	]
	bad = check(cases)
	assert not bad, bad


def test_clear_stack():
	"""s ⌫ drops the whole stack; during an entry, it empties the field instead and the entry stays
	under way."""

	cases = [
		('s⌫', ['1', '2', '3'], '', [], '', []), ('s⌫', ['1', '2', '3'], '45', ['1', '2', '3'], '', []),
		('s⌫', [], '', [], '', []), ('s⌫⌫', ['1', '2', '3'], '45', ['1', '2', '3'], '', []),
		('s⌫s⌫', ['1', '2', '3'], '45', ['1', '2', '3'], '', []), ('s⌫↵s⌫', ['1', '2', '3'], '45', [], '', []),
	]
	bad = check(cases)
	assert not bad, bad


# --- operations -------------------------------------------------------------------------------

def test_arithmetic():
	"""+ − × ÷ in the stack context (28 digits, ROUND_HALF_UP); errors leave the operands in place."""

	cases = [
		('2↵3+', [], '', ['5'], '', []), ('2↵3-', [], '', ['-1'], '', []), ('6↵4*', [], '', ['24'], '', []),
		('1↵3/', [], '', ['0.3333333333333333333333333333'], '', []),
		('2↵3/', [], '', ['0.6666666666666666666666666667'], '', []),
		('5↵3-', [], '', ['2'], '', []),
		('5↵0/', [], '', ['5', '0'], '', ['OPRDIVZRO']), ('0↵0/', [], '', ['0', '0'], '', ['OPRDIVZRO']),
		('9e999999↵10*', [], '', ['9E+999999', '10'], '', ['OPRRESOFW']),
		('1em999999↵1em999999*', [], '', ['1E-999999', '1E-999999'], '', ['OPRRESUFW']),
		('1em999999↵10/', [], '', ['1E-999999', '10'], '', ['OPRRESUFW']),			# exact, but below 1E-999999
		('1em500000↵1em500026*', [], '', ['1E-500000', '1E-500026'], '', ['OPRRESUFW']),
		('1em499999↵1em500000*', [], '', ['1E-999999'], '', []),					# the smallest stored value
		('1m↵0*', [], '', ['0'], '', []), ('.5m↵.5+', [], '', ['0'], '', []),
		('+', ['7'], '', ['7'], '', ['OPRARGMIS']), ('/', [], '', [], '', ['OPRARGMIS']),
	]
	bad = check(cases)
	assert not bad, bad


def test_functions():
	"""1/x, x², √x, yˣ, ˣ√y, ln, eˣ, log, 10ˣ, their results and error codes."""

	cases = [
		('4s1', [], '', ['0.25'], '', []), ('3s1', [], '', ['0.3333333333333333333333333333'], '', []),
		('0s1', [], '', ['0'], '', ['OPRDIVZRO']),
		('3s2', [], '', ['9'], '', []), ('1e500000s2', [], '', ['1E+500000'], '', ['OPRRESOFW']),
		('4v', [], '', ['2'], '', []), ('2v', [], '', ['1.414213562373095048801688724'], '', []),
		('4mv', [], '', ['-4'], '', ['OPRSQRNEG']), ('0v', [], '', ['0'], '', []), ('v', [], '', [], '', ['OPRARGMIS']),
		('2↵10y', [], '', ['1024'], '', []), ('0↵0y', [], '', ['1'], '', []), ('2m↵3y', [], '', ['-8'], '', []),
		('4↵.5y', [], '', ['2'], '', []), ('0↵1my', [], '', ['0', '-1'], '', ['OPRRESINF']),
		('8m↵.5y', [], '', ['-8', '0.5'], '', ['OPRCPXRES']),
		('10↵1000000y', [], '', ['10', '1000000'], '', ['OPRRESOFW']), ('y', ['5'], '', ['5'], '', ['OPRARGMIS']),
		('8↵3sv', [], '', ['2'], '', []), ('8m↵3sv', [], '', ['-2'], '', []), ('1e300↵3sv', [], '', ['1E+100'], '', []),
		('8m↵2sv', [], '', ['-8', '2'], '', ['OPRCPXRES']), ('8↵0sv', [], '', ['8', '0'], '', ['OPRSQRZRO']),
		('0↵2msv', [], '', ['0', '-2'], '', ['OPRRESINF']), ('0↵3sv', [], '', ['0'], '', []),
		('1l', [], '', ['0'], '', []), ('2l', [], '', ['0.6931471805599453094172321215'], '', []),
		('0l', [], '', ['0'], '', ['OPRRESINF']), ('1ml', [], '', ['-1'], '', ['OPRCPXRES']),
		('1sl', [], '', ['2.718281828459045235360287471'], '', []),
		('1e30sl', [], '', ['1E+30'], '', ['OPRRESOFW']), ('m1e30sl', [], '', ['-1E+30'], '', ['OPRRESUFW']),
		('1000g', [], '', ['3'], '', []), ('0g', [], '', ['0'], '', ['OPRRESINF']), ('5mg', [], '', ['-5'], '', ['OPRCPXRES']),
		('2sg', [], '', ['100'], '', []), ('.5sg', [], '', ['3.162277660168379331998893544'], '', []),
		('999999msg', [], '', ['1E-999999'], '', []), ('1000000msg', [], '', ['-1000000'], '', ['OPRRESUFW']),
		('1000027msg', [], '', ['-1000027'], '', ['OPRRESUFW']), ('30000sg', [], '', ['1E+30000'], '', []),
		('999999↵1e999999sv', [], '', ['1.000000000000000000000000000'], '', []),		# 1/x: a huge denominator
		('2↵1e999999my', [], '', ['1.000000000000000000000000000'], '', []),
	]
	bad = check(cases)
	assert not bad, bad


# --- modes ------------------------------------------------------------------------------------

def test_recall_mode():
	"""r + digit recalls that level to level 0; r0 + two digits for 01-99 (00 does nothing); only q,
	Escape, r, Delete and digits act in recall mode; the input field is never touched."""

	four	= ['10', '11', '12', '13']
	twenty	= [str(i) for i in range(100, 120)]
	cases = [
		('r1', four, '', ['10', '11', '13', '12'], '', []), ('r3', four, '', ['11', '12', '13', '10'], '', []),
		('r5', four, '', four, '', ['RCLVLOFW']), ('rr', four, '', four, '', []),
		('r+1', four, '', ['10', '11', '13', '12'], '', []), ('r⌦', four, '12', four, '12', []),
		('r1', four, '12', ['10', '11', '13', '12'], '12', []),
		('r015', twenty, '', [v for v in twenty if v != '104'] + ['104'], '', []),
		('r001', twenty, '', [v for v in twenty if v != '118'] + ['118'], '', []),
		('r000', twenty, '', twenty, '', []), ('r099', twenty, '', twenty, '', ['RCLVLOFW']),
	]
	bad = check(cases)
	assert not bad, bad

	calc = calc_with(four)
	press(calc, keys_of('rsem'))
	assert calc.data['mode'] == 'rcl' and stack_of(calc) == four
	calc = calc_with(twenty)
	press(calc, keys_of('r01'))
	assert calc.data['mode'] == 'rcl' and calc.data['rcl_dgts'] == '1'


def test_shift_mode():
	"""s turns shift on for one key; a key without a shifted function (s, r, Delete included)
	cancels it silently and is ignored."""

	four = ['10', '11', '12', '13']
	cases = [
		('ss', four, '', four, '', []), ('sr', four, '', four, '', []),
		('s3', four, '', four, '', []), ('s33', four, '', four, '3', []),
		('se', four, '5', four, '5', []), ('s+', four, '5', four, '5', []), ('s⌦', four, '5', four, '5', []),
		('s2', four, '7', four + ['49'], '', []),
	]
	bad = check(cases)
	assert not bad, bad
	calc = calc_with(four)
	press(calc, keys_of('sr'))
	assert calc.data['mode'] is None


def test_quit():
	"""q and Escape quit in standard, shift and recall mode."""

	for keys in ('q', '⎋', 'rq', 'r⎋', 'sq', 's⎋'):
		calc = calc_with(['1'])
		press(calc, keys_of(keys))
		assert not calc.sts_running, keys


# --- drawing ----------------------------------------------------------------------------------

def test_value_notation():
	"""Each value is formatted with all the room (pane width − index − ': '): its notation doesn't
	depend on the column's width. Rows are padded to the pane's width."""

	for width in (80, 30, 12):
		calc	= calc_with(stack16(), width=width, height=25)
		drawn	= rows(calc, 'stack')
		levels	= len(calc.data['stack'])
		shown	= min(levels, 20)
		idx_w	= len(str(shown - 1))
		room	= width - idx_w - 2
		fv		= FmtVal()
		for level in range(shown):
			value	= calc.data['stack'][-1 - level]
			want	= fv.run(value, 20, room)
			row		= drawn[-1 - level]
			assert row.split(': ', 1)[1].strip() == want, (width, level, row)
		assert all(len(r) == width for r in drawn), width


def test_display_limits():
	"""A stored value next to the ceiling displays, even when its display rounding carries it
	past 9.99…E999999: 21 nines, typed then pushed, once crashed the redraw (decimal.Overflow)."""

	calc = calc_with()
	press(calc, list('9.99999999999999999999') + ['e'] + list('999999') + ['ENTER'])
	assert stack_of(calc) == ['9.99999999999999999999E+999999']
	assert rows(calc, 'stack')[-1].rstrip() == '0: 1E1000000'

	narrow = calc_with(['9.6E999999'], width=12)						# 9 columns for the value
	assert rows(narrow, 'stack')[-1].rstrip() == '0: 1E1000000'


def test_column():
	"""The value column is as wide as the widest visible value; the input field ends on the values'
	right edge; a longer field widens the column, which stays until the field is emptied."""

	calc = calc_with(stack16())								# widest visible value: 24 characters

	def edges():
		stack	= len(rows(calc, 'stack')[-1].rstrip())
		field	= len(rows(calc, 'input_field')[0].rstrip())
		return stack, field

	press(calc, keys_of('123'))
	assert edges() == (28, 28)
	press(calc, list('1234567890123456789012345') + ['e', '5', '0'])
	assert edges() == (35, 35)								# a 31-character field
	press(calc, keys_of('⌫⌫⌫'))
	assert edges() == (35, 35)								# kept after Backspace
	press(calc, keys_of('↵'))
	assert edges()[0] == 28 and calc.data['inf_colw'] == 0	# back to the stack once emptied

	press(calc, keys_of('12345678901234567890s⌫'))
	assert edges()[0] == 28 and calc.data['inf_colw'] == 0	# s Backspace empties it too

	narrow = calc_with(['1'], width=20)
	press(narrow, list('1234567890123456789012'))
	field = rows(narrow, 'input_field')[0]
	assert len(field.rstrip()) == 20 and '…' in field		# ellipsis at the room


def test_restored_field():
	"""A field restored at startup sets the column at once."""

	calc	= calc_with(stack16(), field='1234567890' * 4)
	stack	= len(rows(calc, 'stack')[-1].rstrip())
	field	= len(rows(calc, 'input_field')[0].rstrip())
	assert stack == field == 4 + 40


def test_bars():
	"""The bar above the field stops at the values' right edge, index included; there's no bar
	below the field any more."""

	for stack, field, want in ((stack16(), '', 28), (stack16(), '1234567890' * 4, 44), (['5'], '', 4), ([], '', 3)):
		calc	= calc_with(stack, field)
		bar		= rows(calc, 'input_top')[0]
		assert bar.rstrip() == '─' * want and len(bar) == 80, (stack[:1], field, bar)
	assert 'input_bottom' not in calc_with().mp.panes


def test_empty_stack():
	"""An empty stack shows level 0 without a value; typing aligns after it."""

	calc	= calc_with(width=30, height=10)
	drawn	= rows(calc, 'stack')
	assert drawn[-1].rstrip() == '0:' and all(len(r) == 30 for r in drawn)
	press(calc, keys_of('42'))
	assert rows(calc, 'input_field')[0].rstrip() == '>  42'


def test_entry_marker():
	"""A '>' in column 0 of the input field while an entry is under way, even emptied; it goes
	once the entry ends. A long entry never reaches it."""

	calc = calc_with(['5'])
	assert rows(calc, 'input_field')[0].strip() == ''
	press(calc, keys_of('12'))
	assert rows(calc, 'input_field')[0].rstrip() == '>  12'
	press(calc, keys_of('⌫⌫'))
	assert rows(calc, 'input_field')[0].rstrip() == '>'
	calc.mp.draw()
	press(calc, keys_of('↵'))
	assert calc.mp.dirty == {'input_field'}				# nothing pushed, only the '>' goes
	assert rows(calc, 'input_field')[0].strip() == ''

	narrow = calc_with(['1'], width=20)
	press(narrow, list('1234567890123456789012'))
	field = rows(narrow, 'input_field')[0]
	assert field.startswith('>  …') and len(field) == 20		# the level numbers' 3 columns, then the field


def test_dirty_panes():
	"""An edit redraws the field; a push the stack and the field; a refused key only the error
	line; a mode change the mode and keys lines; a moving column the three panes drawn on it."""

	calc = calc_with(['5'])
	press(calc, keys_of('7'))								# the column keeps its width: 1
	assert calc.mp.dirty == {'input_field'}
	calc.mp.draw()
	press(calc, keys_of('↵'))
	assert calc.mp.dirty == {'stack', 'input_field'}

	refused = calc_with(['5'])
	press(refused, keys_of('/'))							# OPRARGMIS: only the error shows
	assert refused.mp.dirty == {'error_line'}
	refused.mp.draw()
	press(refused, keys_of('s'))							# the error goes, the mode changes
	assert refused.mp.dirty == {'error_line', 'mode_line', 'keys_line'}
	refused.mp.draw()
	press(refused, keys_of('3'))							# shift cancelled, key ignored
	assert refused.mp.dirty == {'mode_line', 'keys_line'}

	wide = calc_with(['5'])
	press(wide, list('123456789'))							# the column widens
	assert wide.mp.dirty == {'stack', 'input_top', 'input_field'}


def test_layout():
	"""From top to bottom: error line, stack, bar, input field, mode line, keys line."""

	calc	= calc_with(width=80, height=25)
	visible	= [pane for pane in calc.mp.panes if calc.mp.panes[pane][2] and calc.mp.panes[pane][3]]
	order	= sorted(visible, key=lambda pane: calc.mp.panes[pane][1])
	assert order == ['error_line', 'stack', 'input_top', 'input_field', 'mode_line', 'keys_line']
	assert calc.mp.panes['stack'][3] == 19


def test_status_lines():
	"""The mode line shows STD, RCL or SFT; the keys line the mode's keys, cut where the width
	ends; the error line the last key's code, gone at the next key."""

	keys	= RpnCalculator.KEY_LINES
	calc	= calc_with(['5'])
	assert rows(calc, 'mode_line')[0].rstrip() == 'STD'
	assert [row.rstrip() for row in rows(calc, 'keys_line')] == list(keys[None])
	press(calc, keys_of('s'))
	assert rows(calc, 'mode_line')[0].rstrip() == 'SFT'
	assert [row.rstrip() for row in rows(calc, 'keys_line')] == list(keys['sft'])
	press(calc, keys_of('sr'))
	assert rows(calc, 'mode_line')[0].rstrip() == 'RCL'
	assert [row.rstrip() for row in rows(calc, 'keys_line')] == list(keys['rcl'])
	press(calc, keys_of('r'))
	assert rows(calc, 'mode_line')[0].rstrip() == 'STD'

	press(calc, keys_of('/'))
	assert rows(calc, 'error_line')[0].rstrip() == 'OPRARGMIS'
	press(calc, keys_of('7'))
	assert rows(calc, 'error_line')[0].strip() == ''

	narrow = calc_with(['5'], width=5)
	press(narrow, keys_of('/'))
	assert rows(narrow, 'error_line')[0] == 'OPRAR'
	assert rows(narrow, 'keys_line') == [line[:5] for line in keys[None]]


def test_help():
	"""h works in every mode and leaves it as it was; the shifted or recall key still works after."""

	cases = [('h', ['1', '2'], '34', None, ['1', '2'], '34'), ('rh', ['1', '2'], '', 'rcl', ['1', '2'], ''),
			 ('rh1', ['1', '2'], '', None, ['2', '1'], ''), ('sh', ['4'], '', 'sft', ['4'], ''),
			 ('sh1', ['4'], '', None, ['0.25'], '')]
	for keys, stack, field, want_mode, want_stack, want_field in cases:
		calc	= calc_with(stack, field)
		errors	= press(calc, keys_of(keys))
		assert (calc.data['mode'], stack_of(calc), calc.data['in_field'], errors) == (want_mode, want_stack, want_field, []), keys


def test_help_panel():
	"""With the room (the calculator keeps CALC_MINW columns), help goes on the right and the
	calculator keeps working, q still quits. Otherwise help is full screen: the calculator ignores
	the keys, h, q and Escape only hide it. A resize moves it between the two; it's cut at the height."""

	help_w	= max(len(line) for line in RpnCalculator.HELP_LINES) + 1
	side_w	= RpnCalculator.CALC_MINW + 1 + help_w				# 76: calculator, separator, help

	side = calc_with(['5', '6'], width=side_w)
	press(side, keys_of('h'))
	assert side.data['layout'] == 'side'
	assert side.mp.panes['stack'][2] == RpnCalculator.CALC_MINW and side.mp.panes['help'][2] == help_w
	assert rows(side, 'help_sep') == ['│'] * 25
	press(side, keys_of('7+'))
	assert stack_of(side) == ['5', '13']
	press(side, keys_of('h'))
	assert side.data['layout'] == 'calc' and side.mp.panes['stack'][2] == side_w
	press(side, keys_of('hq'))
	assert side.sts_running is False

	full = calc_with(['5', '6'], '12', width=side_w - 1)
	press(full, keys_of('h'))
	assert full.data['layout'] == 'full' and full.mp.panes['help'][2] == side_w - 1
	press(full, keys_of('7+⌫s'))
	assert (stack_of(full), full.data['in_field'], full.data['mode']) == (['5', '6'], '12', None)
	for key in ('q', 'ESC', 'h'):
		press(full, [key])
		assert full.data['layout'] == 'calc' and full.sts_running, key
		press(full, keys_of('h'))
	press(full, keys_of('h'))
	assert len(rows(full, 'input_field')[0].rstrip()) == full.data['col_right']	# the column, set again

	shifted = calc_with(['4'], width=50)
	press(shifted, keys_of('shh1'))								# shift stays across the full-screen help
	assert stack_of(shifted) == ['0.25']

	calc = calc_with(['5'], width=100, height=10)
	press(calc, keys_of('h'))
	assert len(rows(calc, 'help')) == 10						# cut at the height
	assert rows(calc, 'help')[0].rstrip() == ' ' + RpnCalculator.HELP_LINES[0]
	calc.term.width, calc.term.height = 50, 10
	calc.checkresize()
	assert calc.data['layout'] == 'full'
	calc.term.width, calc.term.height = 100, 10
	calc.checkresize()
	assert calc.data['layout'] == 'side'


def test_resize_keeps_column_true():
	"""A resize recomputes the column right away: the recorded right edge matches the drawn one."""

	calc = calc_with(stack16(), field='1234567890' * 4, width=30)
	calc.term = StubTerm()
	calc.data['term_prev_wh'] = (30, 25)
	calc.term.width, calc.term.height = 80, 25
	calc.checkresize()
	idx_w, val_w, col_w, texts = calc.stk_layout()
	assert calc.data['col_right'] == idx_w + 2 + col_w == 44


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
