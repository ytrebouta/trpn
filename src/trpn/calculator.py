"""trpn's calculator: the RpnCalculator class (keys, stack, panes), FmtVal (number display) and start()."""

import os
from time import sleep, monotonic_ns
from decimal import Decimal, Context, ROUND_HALF_UP, Overflow, Underflow, Subnormal, MIN_EMIN, MAX_EMAX
from fractions import Fraction
from blessed import Terminal
from blessed.keyboard import Keystroke
from maupertuis import Maupertuis
from trpn import dmath

# The display's roundings (FmtVal) only write text: their exponent range must never block a
# rounding. Rounding to fewer digits can carry a stored value past the stack's ceiling
# (9.6E999999 at 1 digit is 1E1000000), which Python's default range ±999999 refuses.

DSP_RANGE	= {'Emin': MIN_EMIN, 'Emax': MAX_EMAX}


class RpnCalculator:

	MODE_NAMES	= {None: 'STD', 'rcl': 'RCL', 'sft': 'SFT'}
	KEY_LINES	= {
		None:	('help:h quit:q sft:s rcl:r swap:→',
				 '±:m +-*/ √:v yˣ:y ln:l log:g E:e'),
		'rcl':	('help:h quit:q cancel:r',
				 '1-9 or 0xx'),
		'sft':	('help:h quit:q cancel:s',
				 '1/x:1 x²:2 ˣ√y:v eˣ:l 10ˣ:g CLRSTK:BCK'),
	}
	CALC_MINW	= 40											# columns the calculator keeps beside the help
	HELP_LINES	= (
		'help on/off                h',
		'quit                       q Esc',
		'digits                     0-9',
		'decimal point              .',
		'exponent                   e',
		'sign                       m',
		'push entry / DUP           ↵',
		'delete char / DROP         BCK',
		'clear entry / CLEAR stack  s BCK',
		'SWAP                       →',
		'arithmetic                 + - * /',
		'√x                         v',
		'yˣ                         y',
		'ln                         l',
		'log                        g',
		'1/x                        s 1',
		'x²                         s 2',
		'ˣ√y                        s v',
		'eˣ                         s l',
		'10ˣ                        s g',
		'RECALL level 1-9           r 1-9',
		'RECALL level 01-99         r 0xx',
	)

	def __init__(self, fps=60):

		self.frame_ns		= 1_000_000_000 // fps
		self.data			= {}
		os.system('')
		term				= Terminal()
		self.term			= term
		self.fmtval			= FmtVal()

		self.term.CLEAR_SCROLLBACK	= '\x1b[3J'
		self.clr_str				= term.clear + term.CLEAR_SCROLLBACK + term.home
		self.data['term_prev_wh']	= None
		self.data['in_field']		= ''
		self.data['inf_open']		= False						# an entry under way, even emptied: Backspace edits it, never drops
		self.data['stack']			= []
		self.data['stk_max']		= 100
		self.data['dspmaxsig']		= 20
		self.data['stgsig']			= 28						# digits stored on the stack
		self.data['mode']			= None						# None, 'rcl' (recall) or 'sft' (shift)
		self.data['rcl_dgts']		= None						# after r0: the level's digits typed so far
		self.data['err']			= None						# error code of the last key, shown on the error line
		self.data['inf_colw']		= 0							# width the input field asked for (0: none)
		self.data['col_right']		= None						# right edge of the value column, last computed
		self.data['err_shown']		= None						# error code on the error line, last drawn
		self.data['mode_shown']		= None						# mode on the mode line, last drawn
		self.data['help']			= False						# help shown
		self.data['layout']			= 'calc'					# 'calc', 'side' (help on the right) or 'full' (help alone)
		self.stg_ctx				= Context(prec=self.data['stgsig'], rounding=ROUND_HALF_UP)
		self.sts_running	= True

	def ini(self):

		term		= self.term
		help_w		= max(len(line) for line in self.HELP_LINES) + 1	# a space after the separator

		calc_rows	= {'rows': [
			('error_line',		1),
			('stack',			-1),
			('input_top',		1),
			('input_field',		1),
			('mode_line',		1),
			('keys_line',		2),
		]}

		# the same pane ids in every layout: 0 hides
		self.layouts = {
			'calc':	{'cols': [(calc_rows, -1), ('help_sep', 0), ('help', 0)]},
			'side':	{'cols': [(calc_rows, -1), ('help_sep', 1), ('help', help_w)]},
			'full':	{'cols': [(calc_rows, 0), ('help_sep', 0), ('help', -1)]},
		}

		self.draw_fns = {
			'error_line'	: self.draw_error,
			'stack'			: self.draw_stack,
			'input_top'		: self.draw_bar,
			'input_field'	: self.draw_infield,
			'mode_line'		: self.draw_mode,
			'keys_line'		: self.draw_keys,
			'help_sep'		: self.draw_helpsep,
			'help'			: self.draw_help,
		}

		layout	= self.layouts[self.data['layout']]
		self.mp	= Maupertuis(layout, self.draw_fns, term.width, term.height, self.clr_str)

	def run(self):

		self.ini()
		term = self.term

		self.data['inf_open'] = self.data['in_field'] != ''		# a restored field is an entry under way
		self.checkresize()									# builds the panes and sets the column: a restored field too
		self.sts_update()

		next_frame = monotonic_ns() + self.frame_ns			# the first frame's deadline; the loop then corrects sleep()'s drift

		with term.fullscreen(), term.cbreak(), term.hidden_cursor():
			while self.sts_running:

				# Resize event

				self.checkresize()

				# Key input handling

				key					= term.inkey(timeout=0)
				self.data['key']	= key

				if key:
					self.data['err'] = None						# an error lasts until the next key
					self.keyprocess()
					self.col_update()
					self.sts_update()
					self.data['key'] = None

				# Here is a section to check if anything is dirty and if so, get whatever needs to be displayed.

				out_str				= self.mp.draw()
				print(out_str, end='', flush=True)

				# Frame pacing: sleep until the next frame, at fps frames per second

				now = monotonic_ns()

				if now < next_frame:
					sleep((next_frame - now) / 1e9)

				else:
					next_frame = now			# fell behind: resync, don't burst

				next_frame += self.frame_ns

	def checkresize(self):

		term	= self.term

		tw		= term.width
		th		= term.height

		if self.data['term_prev_wh'] == (tw, th):
			return

		self.data['term_prev_wh']	= (tw, th)

		self.lay_pick(tw)									# side or full help depends on the width
		self.mp.build(tw, th)
		self.col_update()									# the new width can move the column: col_right stays true

	def lay_pick(self, width):
		"""Sets the layout for this width: the calculator alone with help off; with help on, help on
		the right when the calculator keeps CALC_MINW columns beside it, else help full screen.
		The caller builds the panes."""

		help_w	= self.layouts['side']['cols'][2][1]
		side_w	= self.CALC_MINW + 1 + help_w				# calculator, separator, help

		if not self.data['help']:
			name = 'calc'

		elif width >= side_w:
			name = 'side'

		else:
			name = 'full'

		self.data['layout']	= name
		self.mp.layout		= self.layouts[name]

	def keyprocess(self):

		mode	= self.data['mode']
		key		= self.data['key']
		in_ln	= self.data['inf_open']							# an entry under way, even emptied

		if self.data['layout'] == 'full':
			self.key_help()
			return

		if mode == 'rcl':
			self.key_rcl()
			return

		if mode == 'sft':
			self.key_sft()
			return

		match key:

			case 'r':
				self.data['mode'] = 'rcl'

			case 's':
				self.data['mode'] = 'sft'

			case 'h':
				self.fn_help()

			case Keystroke(value='q') | Keystroke(name='KEY_ESCAPE'):
				self.sts_running = False

			case '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '0':
				self.data['inf_open'] = True						# an entry starts or goes on
				self.fn_dgtadd()

			case 'e':
				self.data['inf_open'] = True
				self.fn_exp()

			case '.':
				self.data['inf_open'] = True
				self.fn_dot()

			case 'm':
				self.data['inf_open'] = True
				self.fn_sign()

			case Keystroke(name='KEY_ENTER'):
				if in_ln:
					self.fn_tostack()
				else:
					self.fn_dup()

			case Keystroke(name='KEY_BACKSPACE'):
				if in_ln:
					self.fn_dgtdel()								# an entry under way: the stack is out of reach
				else:
					self.fn_drop()

			case Keystroke(name='KEY_RIGHT'):
				if in_ln and not self.fn_tostack():				# a pending entry is pushed first
					return
				self.fn_swap()

			case '+':
				if in_ln and not self.fn_tostack():				# a pending entry is pushed first
					return
				self.fn_add()

			case '-':
				if in_ln and not self.fn_tostack():
					return
				self.fn_sub()

			case '*':
				if in_ln and not self.fn_tostack():
					return
				self.fn_mul()

			case '/':
				if in_ln and not self.fn_tostack():
					return
				self.fn_div()

			case 'y':
				if in_ln and not self.fn_tostack():
					return
				self.fn_power()

			case 'v':
				if in_ln and not self.fn_tostack():
					return
				self.fn_sqrt()

			case 'l':
				if in_ln and not self.fn_tostack():
					return
				self.fn_ln()

			case 'g':
				if in_ln and not self.fn_tostack():
					return
				self.fn_log()

	def mode_off(self):
		"""Leaves recall or shift mode."""

		self.data['mode']		= None
		self.data['rcl_dgts']	= None

	def key_help(self):
		"""Keys with the help full screen: h, q and Escape hide it; the calculator ignores the rest."""

		key = self.data['key']

		match key:

			case 'h' | Keystroke(value='q') | Keystroke(name='KEY_ESCAPE'):
				self.fn_help()

	def key_rcl(self):
		"""Keys in recall mode: a level number recalls that level to level 0. q quits, h toggles the
		help (recall stays on), r and Delete cancel; every other key is ignored."""

		key = self.data['key']

		match key:

			case Keystroke(value='q') | Keystroke(name='KEY_ESCAPE'):
				self.sts_running = False

			case 'h':
				self.fn_help()								# recall stays on

			case 'r' | Keystroke(name='KEY_DELETE'):
				self.mode_off()

			case '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9':
				self.rcl_digit()

	def rcl_digit(self):
		"""A digit in recall mode. 1-9 recalls that level at once; 0 announces a two-digit level,
		given by the next two digits: r0 15 is level 15, r0 01 level 1, r0 00 does nothing."""

		key		= self.data['key']
		digits	= self.data['rcl_dgts']

		if digits is None:									# first digit after r
			if key == '0':
				self.data['rcl_dgts'] = ''					# wait for two more digits
				return
			level = int(key)
		else:												# after r0
			digits += key
			if len(digits) < 2:
				self.data['rcl_dgts'] = digits
				return
			level = int(digits)

		if level > 0:										# level 0 is already at level 0
			self.fn_recall(level)

		self.mode_off()										# one-shot, done or refused

	def fn_recall(self, level):
		"""Recalls stack level `level` to level 0: moved, not copied; the levels below it each move up
		one level. A level beyond the stack gives RCLVLOFW."""

		stack = self.data['stack']

		if level >= len(stack):
			self.data['err'] = 'RCLVLOFW'
			return

		index	= len(stack) - 1 - level					# level 0 is the last item
		value	= stack.pop(index)
		stack.append(value)
		self.mp.mark('stack')

	def key_sft(self):
		"""Keys in shift mode: one shifted function, then shift turns off. q quits; any other key
		except h cancels shift silently."""

		key		= self.data['key']
		in_ln	= self.data['inf_open']							# an entry under way, even emptied

		if key == 'h':										# help leaves shift on: look, then press the shifted key
			self.fn_help()
			return

		self.mode_off()										# one-shot, whatever the key

		match key:

			case Keystroke(value='q') | Keystroke(name='KEY_ESCAPE'):
				self.sts_running = False

			case '1':
				if in_ln and not self.fn_tostack():			# a pending entry is pushed first
					return
				self.fn_inv()

			case '2':
				if in_ln and not self.fn_tostack():
					return
				self.fn_sq()

			case 'v':
				if in_ln and not self.fn_tostack():
					return
				self.fn_root()

			case 'l':
				if in_ln and not self.fn_tostack():
					return
				self.fn_powe()

			case 'g':
				if in_ln and not self.fn_tostack():
					return
				self.fn_pow10()

			case Keystroke(name='KEY_BACKSPACE'):
				if in_ln:
					self.fn_infclear()								# an entry under way: the stack is out of reach
				else:
					self.fn_clearstack()

	def stk_chkargs(self, count):
		"""True when the stack holds at least `count` levels, else OPRARGMIS."""

		if len(self.data['stack']) < count:
			self.data['err'] = 'OPRARGMIS'
			return False

		return True

	def opr_ctx(self):
		"""A copy of the stack context for one operation: its own flags, cleared, and Overflow as a
		flag instead of an exception, so that opr_store checks overflow and underflow alike."""

		ctx = self.stg_ctx.copy()
		ctx.clear_flags()
		ctx.traps[Overflow] = False
		return ctx

	def opr_store(self, ctx, result, count):
		"""Puts an operation's result in place of its `count` operands. An overflow (OPRRESOFW) or a
		result below 1E-999999, exact or not (OPRRESUFW), leaves the operands in place. −0 is
		stored as 0."""

		if ctx.flags[Overflow]:
			self.data['err'] = 'OPRRESOFW'
			return

		if ctx.flags[Underflow] or ctx.flags[Subnormal]:		# Underflow alone lets exact subnormals through
			self.data['err'] = 'OPRRESUFW'
			return

		if result == 0:										# never −0
			result = Decimal(0)

		stack			= self.data['stack']
		stack[-count:]	= [result]
		self.mp.mark('stack')

	def fn_add(self):
		"""+: level 1 + level 0."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		level1	= stack[-2]
		level0	= stack[-1]
		ctx		= self.opr_ctx()
		result	= ctx.add(level1, level0)
		self.opr_store(ctx, result, 2)

	def fn_sub(self):
		"""-: level 1 − level 0."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		level1	= stack[-2]
		level0	= stack[-1]
		ctx		= self.opr_ctx()
		result	= ctx.subtract(level1, level0)
		self.opr_store(ctx, result, 2)

	def fn_mul(self):
		"""*: level 1 × level 0."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		level1	= stack[-2]
		level0	= stack[-1]
		ctx		= self.opr_ctx()
		result	= ctx.multiply(level1, level0)
		self.opr_store(ctx, result, 2)

	def fn_div(self):
		"""/: level 1 ÷ level 0. Level 0 = 0 gives OPRDIVZRO (0 ÷ 0 included)."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		level1	= stack[-2]
		level0	= stack[-1]

		if level0 == 0:
			self.data['err'] = 'OPRDIVZRO'
			return

		ctx		= self.opr_ctx()
		result	= ctx.divide(level1, level0)
		self.opr_store(ctx, result, 2)

	def fn_inv(self):
		"""s1: 1/x. x = 0 gives OPRDIVZRO."""

		if not self.stk_chkargs(1):
			return

		x = self.data['stack'][-1]

		if x == 0:
			self.data['err'] = 'OPRDIVZRO'
			return

		ctx		= self.opr_ctx()
		result	= ctx.divide(Decimal(1), x)
		self.opr_store(ctx, result, 1)

	def fn_sq(self):
		"""s2: x²."""

		if not self.stk_chkargs(1):
			return

		x		= self.data['stack'][-1]
		ctx		= self.opr_ctx()
		result	= ctx.multiply(x, x)
		self.opr_store(ctx, result, 1)

	def fn_sqrt(self):
		"""v: √x. x < 0 gives OPRSQRNEG. Decimal's sqrt is correctly rounded (half-even, which
		never differs from half-up here: a square root never falls exactly halfway)."""

		if not self.stk_chkargs(1):
			return

		x = self.data['stack'][-1]

		if x < 0:
			self.data['err'] = 'OPRSQRNEG'
			return

		ctx		= self.opr_ctx()
		result	= ctx.sqrt(x)
		self.opr_store(ctx, result, 1)

	def fn_power(self):
		"""y: yˣ, y on level 1, x on level 0. 0⁰ = 1. 0 to a negative power gives OPRRESINF, a
		negative y with a non-integer x OPRCPXRES."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		y		= stack[-2]
		x		= stack[-1]
		x_frac	= Fraction(x)								# exact: tells integers apart

		if y == 0 and x < 0:
			self.data['err'] = 'OPRRESINF'
			return

		if y < 0 and x_frac.denominator != 1:
			self.data['err'] = 'OPRCPXRES'
			return

		ctx		= self.opr_ctx()
		result	= dmath.power(y, x, ctx=ctx)
		self.opr_store(ctx, result, 2)

	def fn_root(self):
		"""sv: ˣ√y, y on level 1, x on level 0. x = 0 gives OPRSQRZRO; the root of 0 with x < 0
		OPRRESINF; a negative y needs an odd integer x, else OPRCPXRES."""

		if not self.stk_chkargs(2):
			return

		stack	= self.data['stack']
		y		= stack[-2]
		x		= stack[-1]
		x_frac	= Fraction(x)

		if x == 0:
			self.data['err'] = 'OPRSQRZRO'
			return

		if y == 0 and x < 0:
			self.data['err'] = 'OPRRESINF'
			return

		if y < 0:
			odd_integer = x_frac.denominator == 1 and x_frac.numerator % 2 == 1
			if not odd_integer:
				self.data['err'] = 'OPRCPXRES'
				return

		ctx		= self.opr_ctx()
		result	= dmath.root(y, x, ctx=ctx)
		self.opr_store(ctx, result, 2)

	def fn_ln(self):
		"""l: ln x. x = 0 gives OPRRESINF, x < 0 OPRCPXRES."""

		if not self.stk_chkargs(1):
			return

		x = self.data['stack'][-1]

		if x == 0:
			self.data['err'] = 'OPRRESINF'
			return

		if x < 0:
			self.data['err'] = 'OPRCPXRES'
			return

		ctx		= self.opr_ctx()
		result	= dmath.ln(x, ctx=ctx)
		self.opr_store(ctx, result, 1)

	def fn_powe(self):
		"""sl: eˣ."""

		if not self.stk_chkargs(1):
			return

		x		= self.data['stack'][-1]
		ctx		= self.opr_ctx()
		result	= dmath.exp(x, ctx=ctx)
		self.opr_store(ctx, result, 1)

	def fn_log(self):
		"""g: log x, base 10. x = 0 gives OPRRESINF, x < 0 OPRCPXRES."""

		if not self.stk_chkargs(1):
			return

		x = self.data['stack'][-1]

		if x == 0:
			self.data['err'] = 'OPRRESINF'
			return

		if x < 0:
			self.data['err'] = 'OPRCPXRES'
			return

		ctx		= self.opr_ctx()
		result	= dmath.log10(x, ctx=ctx)
		self.opr_store(ctx, result, 1)

	def fn_pow10(self):
		"""sg: 10ˣ."""

		if not self.stk_chkargs(1):
			return

		x		= self.data['stack'][-1]
		ctx		= self.opr_ctx()
		result	= dmath.power(Decimal(10), x, ctx=ctx)
		self.opr_store(ctx, result, 1)

	def stk_layout(self):
		"""Geometry shared by the stack and the input field, from the stack pane: (idx_w, val_w,
		col_w, texts). col_w is the value column: as wide as the widest visible value, or as the
		input field's sticky width when larger, never wider than the room. texts are the visible
		values, each formatted with all the room."""

		x0, y0, w, h	= self.mp.panes['stack']
		fv				= self.fmtval
		stack			= self.data['stack']
		sig				= self.data['dspmaxsig']

		levels	= min(h, len(stack))						# levels that fit in the pane
		shown	= max(levels, 1)							# an empty stack still shows level 0
		idx_w	= len(str(shown - 1))						# index digits: 2 for 10 to 99 levels
		val_w	= w - idx_w - 2								# room for a value: what's left after the index and ': '

		# each visible value formatted with all the room, so its notation doesn't depend on the others
		texts = []
		for level in range(levels):
			val = stack[-1 - level]							# level 0 is the last pushed
			texts.append(fv.run(val, sig, val_w))

		col_w = max((len(txt) for txt in texts), default=0)	# the widest visible value sets the column
		col_w = max(col_w, self.data['inf_colw'])			# unless the input field asked for more
		col_w = min(col_w, val_w)							# never beyond the room

		return idx_w, val_w, col_w, texts

	def col_update(self):
		"""After a key: the input field's sticky width grows with the field, stays when it shrinks,
		and goes once the field is emptied. When the column's right edge moves (that width, a wider
		or narrower value on the stack, 10 levels reached), every pane drawn on it is redrawn.
		Nothing to do when neither the stack nor the field changed, unless a full redraw is pending
		(startup, resize): a field restored at startup sets the column too. Nothing either while the
		help hides the stack: leaving it rebuilds the panes, and sets the column."""

		mp				= self.mp
		changed			= mp.full_redraw or 'stack' in mp.dirty or 'input_field' in mp.dirty
		x0, y0, w, h	= mp.panes['stack']

		if not changed or w == 0:
			return											# the column depends on nothing that changed, or there's none

		in_len	= len(self.data['in_field'])
		sticky	= self.data['inf_colw']

		if in_len == 0:
			sticky = 0										# field emptied: the stack decides again
		elif in_len > sticky:
			sticky = in_len

		self.data['inf_colw'] = sticky

		idx_w, val_w, col_w, texts	= self.stk_layout()
		right						= idx_w + 2 + col_w		# the values' right edge, from the pane's left

		if right != self.data['col_right']:
			self.data['col_right'] = right
			mp.mark('stack')
			mp.mark('input_top')
			mp.mark('input_field')

	def draw_bar(self, x0, y0, w, h):
		"""The bar above the input field."""

		term							= self.term
		idx_w, val_w, col_w, texts		= self.stk_layout()
		right							= idx_w + 2 + col_w
		bar								= '─' * right

		return term.move_xy(x0, y0) + f"{bar:<{w}}"			# padded to the pane: erases a longer old bar

	def fn_help(self):
		"""h: shows or hides the help, in every mode, without changing it. With the room, help goes
		on the right and the calculator keeps working beside it; else it takes the whole screen."""

		self.data['help'] = not self.data['help']

		self.lay_pick(self.mp.width)
		self.mp.build()										# a full redraw, at the same size
		self.col_update()

	def sts_update(self):
		"""After a key: redraws the error line when the error changed (a new code, or the last one
		gone: an error lasts until the next key), the mode and keys lines when the mode changed."""

		err		= self.data['err']
		mode	= self.data['mode']

		if err != self.data['err_shown']:
			self.data['err_shown'] = err
			self.mp.mark('error_line')

		if mode != self.data['mode_shown']:
			self.data['mode_shown'] = mode
			self.mp.mark('mode_line')
			self.mp.mark('keys_line')

	def draw_error(self, x0, y0, w, h):
		"""The error line, at the top: the last key's error code, empty otherwise."""

		term	= self.term
		err		= self.data['err']
		text	= err if err is not None else ''
		text	= text[:w]									# cut where the width ends

		return term.move_xy(x0, y0) + f"{text:<{w}}"		# padded to the pane: erases a longer old code

	def draw_mode(self, x0, y0, w, h):
		"""The mode line: STD, RCL or SFT."""

		term	= self.term
		text	= self.MODE_NAMES[self.data['mode']]
		text	= text[:w]

		return term.move_xy(x0, y0) + f"{text:<{w}}"

	def draw_keys(self, x0, y0, w, h):
		"""The keys lines: the current mode's keys, one row each, cut where the width ends."""

		term	= self.term
		lines	= self.KEY_LINES[self.data['mode']]
		out		= ''

		for row, text in enumerate(lines[:h]):
			text	= text[:w]
			out		+= term.move_xy(x0, y0 + row) + f"{text:<{w}}"

		return out

	def draw_helpsep(self, x0, y0, w, h):
		"""The separator between the calculator and the help on its right: a vertical line."""

		term	= self.term
		out		= ''

		for row in range(h):
			out += term.move_xy(x0, y0 + row) + '│'

		return out

	def draw_help(self, x0, y0, w, h):
		"""The help: one function per row, cut where the width and the height end."""

		term	= self.term
		lines	= self.HELP_LINES
		out		= ''

		for row in range(h):
			text	= ' ' + lines[row] if row < len(lines) else ''		# rows past the help: blank
			text	= text[:w]
			out		+= term.move_xy(x0, y0 + row) + f"{text:<{w}}"

		return out

	def draw_stack(self, x0, y0, w, h):

		term							= self.term
		idx_w, val_w, col_w, texts		= self.stk_layout()
		levels							= len(texts)
		shown							= max(levels, 1)	# an empty stack still shows level 0
		blank							= ' ' * w			# a whole empty row
		out								= ''

		for row in range(h - shown):						# empty rows above the stack, from the top of the pane
			out		+= term.move_xy(x0, y0 + row) + blank

		if levels == 0:										# level 0 without a value: a visual help
			line	 = f"{0:>{idx_w}}: "
			out		+= term.move_xy(x0, y0 + h - 1) + f"{line:<{w}}"

		for level in range(levels):
			txt		 = texts[level]
			y		 = y0 + h - 1 - level					# level 0 on the bottom row
			line	 = f"{level:>{idx_w}}: {txt:>{col_w}}"	# right-aligned in the column
			out		+= term.move_xy(x0, y) + f"{line:<{w}}"	# padded to the pane: erases a longer old line

		return out

	def draw_infield(self, x0, y0, w, h):

		term							= self.term
		in_field						= self.data['in_field']
		idx_w, val_w, col_w, texts		= self.stk_layout()

		if len(in_field) > val_w:							# longer than a value's room: ellipsis
			keep		= val_w - 1
			tail		= in_field[len(in_field) - keep:]
			in_field	= '…' + tail

		marker	= '>' if self.data['inf_open'] else ' '		# an entry under way, even emptied
		right	= idx_w + 2 + col_w							# right edge on the values' right edge
		line	= marker + f"{in_field:>{right - 1}}"		# column 0 is under the level numbers: never the field's

		return term.move_xy(x0, y0) + f"{line:<{w}}"		# padded to the pane: erases a longer old field

	def inf_chkexpbnd(self, text):
		"""Checks exponent boundaries: False when text, a complete number, would have its first digit
		beyond the stack context's exponent limits (±999999). Incomplete text ('1E', '1E-') passes:
		the push drops an exponent without digits."""

		mantissa, e_mark, exponent	= text.partition('E')
		exp_digits					= exponent.replace('-', '')

		if not exp_digits:
			return True

		value = Decimal(text)										# exact: a string needs no context
		if value == 0:
			return True

		adjusted	= value.adjusted()								# exponent of the first digit
		stg_ctx		= self.stg_ctx
		return stg_ctx.Emin <= adjusted <= stg_ctx.Emax

	def inf_validate(self):
		"""The input field's value as a Decimal, completing what's unfinished: no mantissa digit
		('-', '.', '-.') gives 0, an exponent without digit ('1E', '1E-') is dropped, and a zero
		is always 0, never −0. The keys' rules keep the rest valid: at most stgsig significant
		digits and an exponent within bounds, so the conversion is exact."""

		infield		= self.data['in_field']

		mantissa, e_mark, exponent	= infield.partition('E')
		mant_digits					= mantissa.replace('-', '').replace('.', '')
		exp_digits					= exponent.replace('-', '')

		if not mant_digits:											# '-', '.', '-.'
			return Decimal(0)

		if exp_digits:
			text = infield
		else:														# '1E', '1E-': the mantissa alone
			text = mantissa

		value = Decimal(text)										# exact: a string needs no context

		if value == 0:												# -0, -0.0, 0E5
			return Decimal(0)

		return value

	def fn_infclear(self):
		"""s Backspace during an entry: empties the input field. The entry stays under way."""

		self.data['in_field'] = ''
		self.mp.mark('input_field')

	def fn_dgtadd(self):
		"""A digit: added to the exponent once there's an E, to the mantissa before."""

		infield		= self.data['in_field']
		key			= self.data['key']

		mantissa, e_mark, exponent	= infield.partition('E')		# '-1.5E-25' -> '-1.5', 'E', '-25'

		if e_mark:
			new_infield = infield + key
			if not self.inf_chkexpbnd(new_infield):
				self.data['err'] = 'INFEXPMAX'
				return
		else:
			mant_digits	= mantissa.replace('-', '').replace('.', '')
			significant	= mant_digits.lstrip('0')					# leading zeros don't count
			if len(significant) >= self.data['stgsig']:				# no more digits than the stack holds
				self.data['err'] = 'INFDGTMAX'
				return
			new_infield = infield + key

		self.data['in_field'] = new_infield
		self.mp.mark('input_field')

	def fn_exp(self):
		"""'e': starts the exponent ('E'). Removes it again, with its sign, while no exponent digit
		follows. With no mantissa digit yet, inserts 1E as the HP48 does ('-' gives '-1E')."""

		infield		= self.data['in_field']

		mantissa, e_mark, exponent	= infield.partition('E')
		mant_digits					= mantissa.replace('-', '').replace('.', '')

		if e_mark:
			if exponent in ('', '-'):								# nothing after E but its sign: toggled back off
				self.data['in_field'] = mantissa
				self.mp.mark('input_field')
			else:
				self.data['err'] = 'INFEXPDUP'
			return

		if not mant_digits:											# nothing typed but a sign or a dot
			sign		= '-' if mantissa.startswith('-') else ''
			infield		= sign + '1E'
		else:
			infield		= infield + 'E'

		self.data['in_field'] = infield
		self.mp.mark('input_field')

	def fn_dot(self):
		"""'.': the mantissa's decimal point. Removes it again if it's the last character."""

		infield		= self.data['in_field']

		mantissa, e_mark, exponent	= infield.partition('E')

		if e_mark:
			self.data['err'] = 'INFEXPDOT'							# an exponent has no decimals
			return

		if '.' in mantissa:
			if infield.endswith('.'):								# toggled back off
				self.data['in_field'] = infield[:-1]
				self.mp.mark('input_field')
			else:
				self.data['err'] = 'INFDOTDUP'
			return

		self.data['in_field'] = infield + '.'
		self.mp.mark('input_field')

	def fn_sign(self):
		"""'m': toggles the exponent's sign once there's an E, the mantissa's sign before."""

		infield = self.data['in_field']
		mantissa, e_mark, exponent = infield.partition('E')

		if e_mark:
			if exponent.startswith('-'):
				exponent = exponent[1:]
			else:
				exponent = '-' + exponent
			new_infield = mantissa + 'E' + exponent
			if not self.inf_chkexpbnd(new_infield):					# 0.01E999999 -> 0.01E-999999 = 1E-1000001
				self.data['err'] = 'INFEXPMAX'
				return
		else:
			if mantissa.startswith('-'):
				new_infield = mantissa[1:]
			else:
				new_infield = '-' + mantissa

		self.data['in_field'] = new_infield
		self.mp.mark('input_field')

	def fn_dgtdel(self):
		"""Backspace during an entry: removes the input field's last character. Once the field is
		empty, nothing more: the entry stays under way, so Backspace can't reach the stack."""

		infield = self.data['in_field']

		self.data['in_field'] = infield[:-1]
		self.mp.mark('input_field')

	def fn_tostack(self):
		"""Ends the entry under way: pushes the input field's value and empties the field; an emptied
		field pushes nothing. Returns False when the stack is full (PSHSTKFUL): nothing is pushed and
		the entry stays under way, in the field."""

		stack = self.data['stack']

		if self.data['in_field'] == '':
			self.data['inf_open'] = False						# nothing to push: the entry just ends
			self.mp.mark('input_field')							# the '>' goes
			return True

		if len(stack) >= self.data['stk_max']:
			self.data['err'] = 'PSHSTKFUL'
			return False

		value = self.inf_validate()
		stack.append(value)

		self.data['in_field'] = ''
		self.data['inf_open'] = False
		self.mp.mark('stack')
		self.mp.mark('input_field')
		return True

	def fn_dup(self):
		"""Duplicates level 0."""

		stack = self.data['stack']

		if len(stack) == 0:
			self.data['err'] = 'OPRARGMIS'
			return

		if len(stack) >= self.data['stk_max']:
			self.data['err'] = 'PSHSTKFUL'
			return

		stack.append(stack[-1])
		self.mp.mark('stack')

	def fn_drop(self):
		"""Removes level 0."""

		stack = self.data['stack']

		if len(stack) == 0:
			self.data['err'] = 'OPRARGMIS'
			return

		stack.pop()
		self.mp.mark('stack')

	def fn_clearstack(self):
		"""s Backspace with no entry under way: drops the whole stack."""

		self.data['stack'].clear()
		self.mp.mark('stack')

	def fn_swap(self):
		"""Exchanges levels 0 and 1."""

		stack = self.data['stack']

		if len(stack) < 2:
			self.data['err'] = 'OPRARGMIS'
			return

		level0		= stack[-1]
		level1		= stack[-2]
		stack[-1]	= level1
		stack[-2]	= level0
		self.mp.mark('stack')


class FmtVal:

	def __init__(self, val=None, sig=20, width=30):

		self.val	= val
		self.sig	= sig
		self.width	= width

		if isinstance(val, Decimal):
			self.run()

	def reset(self):

		self.dec_r	= None	# Decimal register
		self.fix_r	= ''	# Text register: dec_r in fixed notation
		self.sci_r	= ''	# Text register: dec_r in scientific notation
		self.txt_r	= ''	# Text register: fix_r or sci_r, as it would be displayed
		self.data	= {}	# Values kept between steps (full precision, candidates)
		self.out	= None	# Final value returned to caller

	def run(self, val=None, sig=None, width=None):

		if val is not None:
			self.val = val
		if sig is not None:
			self.sig = sig
		if width is not None:
			self.width = width

		self.reset()
		self.tryfullprec()

		if self.out:
			return self.out

		self.storefullprec()
		self.trycand1()
		self.trycand2()
		self.choose()

		return self.out

	def fixed_str(self):
		"""Converts Decimal .dec_r to fixed notation in .fix_r, without leading zero (HP style)."""

		dec = self.dec_r

		sign	= '-' if dec < 0 else ''
		digits	= ''.join(map(str, dec.as_tuple().digits))
		e		= dec.adjusted()							# power of ten of the first digit

		if e >= 0:
			n_int	= e + 1									# digits before the dot: e = 2 gives 3 (123.45)
			int_str	= digits[:n_int].ljust(n_int, '0')		# right-pad with zeros if len(digits) < n_int. Example: with int part of 5500: 55 -> 5500
			decs	= digits[n_int:]						# the remaining digits that go after the dot
		else:
			zeros	= abs(e) - 1							# number of zeros after the dot, before the first significant digit.
			int_str	= ''									# no leading zero, HP style: .5, not 0.5
			decs	= '0' * zeros + digits

		frac		= '.' + decs if decs else ''				# no dot for an integer: 123, not 123.
		self.fix_r	= sign + int_str + frac

	def sci_str(self):
		"""Converts Decimal .dec_r to scientific notation in .sci_r: first digit, dot, other digits, E and exponent."""

		dec			= self.dec_r
		sign		= '-' if dec < 0 else ''
		digits		= ''.join(map(str, dec.as_tuple().digits))
		first		= digits[0]							# the only digit before the dot
		rest		= digits[1:]						# the other significant digits, after the dot
		frac		= '.' + rest if rest else ''		# no dot for a single digit: 1E12, not 1.E12
		exp			= f"E{dec.adjusted()}"				# power of ten of the first digit: E12, E-5
		self.sci_r	= sign + first + frac + exp

	def str_val(self):
		"""Sets .txt_r to .fix_r if fixed notation is allowed (at most sig digit positions) and it fits, else to .sci_r."""

		sig			= self.sig
		width		= self.width
		d			= self.dec_r
		e			= d.adjusted()					# power of ten of the first digit
		n_digits	= len(d.as_tuple().digits)		# significant digits

		if e >= 0:
			# Value >= 1: count the integer digits. The first digit is worth 10**e,
			# so there are e + 1 digits before the dot (e = 2: 123.45 has 3).
			positions	= e + 1
		else:
			zeros		= abs(e) - 1					# number of zeros after the dot, before the first significant digit.
			positions	= zeros + n_digits

		if positions <= sig:
			if len(self.fix_r) <= width:
				self.txt_r = self.fix_r
				return

		self.txt_r = self.sci_r

	def tryfullprec(self):

		val			= self.val
		sig			= self.sig
		width		= self.width

		ctx			= Context(prec=sig, rounding=ROUND_HALF_UP, **DSP_RANGE)
		self.dec_r	= val.normalize(ctx)
		self.fixed_str()								# fix_r: full precision, fixed
		self.sci_str()									# sci_r: full precision, scientific
		self.str_val()									# txt_r: fix_r or sci_r
		txt_r = self.txt_r
		if len(txt_r) <= width:
			self.out = txt_r

	def storefullprec(self):
		"""Keeps what the candidates need from full precision, before they reuse the register."""

		data			= self.data
		data['fp_fix']	= self.fix_r					# candidate 1: integer part and dot (partition)
		data['fp_dec']	= self.dec_r					# candidate 2: sign and exponent characters

	def trycand1(self):
		"""Candidate 1: val with its decimals rounded off until it fits, if the integer part fits.
		Rounds val again, not the full-precision value (already rounded to sig), to avoid double rounding.
		Writes on the register; keeps the result in data['cand1_dec'], ['cand1_txt'], ['cand1_res']."""

		val			= self.val
		sig			= self.sig
		width		= self.width
		data		= self.data

		data['cand1_dec']	= None						# stays None when there is no candidate 1

		int_part, dot, _	= data['fp_fix'].partition('.')
		room				= width - len(int_part)		# columns left for the dot and decimals

		if not dot or room < 0:
			return										# integer, or integer part too wide: no candidate 1

		int_digits	= len(int_part.lstrip('-'))			# digits before the dot
		fit_dec		= room - 1							# decimals that fit: the dot takes one column
		sig_dec		= sig - int_digits					# decimals allowed by sig digit positions
		decimals	= max(0, min(fit_dec, sig_dec))
		quantum		= Decimal((0, (1,), -decimals))				# 1E-decimals, exact: no context
		ctx			= Context(prec=sig, rounding=ROUND_HALF_UP, **DSP_RANGE)	# at most sig digits: integer digits + decimals

		self.dec_r	= val.quantize(quantum, context=ctx).normalize(ctx)
		if self.dec_r == 0:
			return										# rounded off to zero: no candidate 1

		self.fixed_str()								# fix_r: candidate 1, fixed
		self.sci_str()									# sci_r: candidate 1, scientific
		self.str_val()									# txt_r: fix_r or sci_r
		if len(self.txt_r) > width:
			return										# too wide once written (carry: 9.996 -> 10 in 1 column): no candidate 1

		data['cand1_dec']	= self.dec_r
		data['cand1_txt']	= self.txt_r
		data['cand1_res']	= -decimals					# resolution: exponent of the last decimal

	def trycand2(self):
		"""Candidate 2: val in scientific notation, mantissa shortened until it fits.
		Rounds val again, not the full-precision value (already rounded to sig), to avoid double rounding.
		Writes on the register; keeps the result in data['cand2_dec'], ['cand2_txt'], ['cand2_res'], ['cand2_fits'].
		Always exists: val isn't zero here, since zero always fits at full precision."""

		val			= self.val
		width		= self.width
		data		= self.data
		fp_dec		= data['fp_dec']

		sign_len	= 1 if fp_dec < 0 else 0			# '-' takes a column
		exp_len		= len(f"E{fp_dec.adjusted()}")		# 'E' and the exponent: E-5 = 3
		sign_exp	= sign_len + exp_len				# sign and exponent characters
		mantissa	= max(1, width - sign_exp - 1)		# digits that fit, next to the dot
		ctx			= Context(prec=mantissa, rounding=ROUND_HALF_UP, **DSP_RANGE)
		short		= ctx.plus(val)
		self.dec_r	= short.normalize(ctx)
		self.fixed_str()								# fix_r: candidate 2, fixed
		self.sci_str()									# sci_r: candidate 2, scientific
		self.str_val()									# txt_r: fix_r or sci_r

		data['cand2_dec']	= self.dec_r
		data['cand2_txt']	= self.txt_r
		data['cand2_res']	= short.as_tuple().exponent	# resolution: exponent of the last mantissa digit
		data['cand2_fits']	= len(self.txt_r) <= width

	def choose(self):
		"""Keeps the finest resolution (smallest last-digit exponent) among the candidates that fit,
		candidate 1 on a tie. When nothing fits, out is filled with # (not even one digit fits)."""

		width		= self.width
		data		= self.data
		cand1_ok	= data['cand1_dec'] is not None

		if cand1_ok:
			cand2_too_wide	= not data['cand2_fits']
			cand1_finer		= data['cand1_res'] <= data['cand2_res']	# finer or same resolution: candidate 1 wins the tie
			if cand2_too_wide or cand1_finer:
				self.out = data['cand1_txt']
				return

		if data['cand2_fits']:
			self.out = data['cand2_txt']
			return

		self.out = '#' * width							# not even one digit fits


def start():
	"""Runs the calculator: the trpn command, python -m trpn, and python calculator.py."""

	calc = RpnCalculator()
	calc.run()


if __name__ == '__main__':
	start()
