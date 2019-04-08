import pandas as pd
import numpy as np
from gurobipy import *

import datetime
import matplotlib.pyplot as plt
import seaborn as sns
sns.set_style("whitegrid")

import os
# Get project directory and load BatteryDefns
PathProj = os.path.dirname(__file__)
BatteryDefns = pd.read_pickle("{}//Input//BatteryDefns.pkl".format(PathProj))

# My Modules
import markettime as mt
CA_time = mt.CA_time

# Options
options = {
	'Currency': 'USD',
}


class batopt():
	"""Battery model for energy arbitrage.

	PROBLEM DEFINITION
		An optimization problem is defined that maximizes the revenue earned by the battery out of energy arbitrage (
		only one of the battery revenue streams). The model is based on the following information:

		1) Battery model
		The batter models are defined in batopt.BatteryDefns. This table defines the specs of each battery system.

		2) Prices
		Arbitrage is fundamentally linked to the price profile. The prices are set via the instance method
		set_prices(), wherein an iterable of prices, together with information on time, is passed. The optimization
		problem is then defined over the entire* period.

		*If you have wish to separately optimize sub-periods (e.g. months of a year), you have to load the periods
		separately.


	TIME
		The time vector is implemented via a RANGE INDEX (of self.dv_vecs, self.dv_soln), wherein the
		actual time information is inferred from the starting time (self.start_time) as processed by the market time
		format (self.market_time).

		Thus, batopt implements the ff. instance methods to facilitate this:

			instance.Market_toIdx()     -- Converts a market TimeStamp to the index along the range index
										Wrapper of self.market_time.Market_toGMT(); pls. pass the same arguments.

			instance.Idx_toMarket()     -- Converts an index along the range index to the market TimeStamp



	"""
	def __init__(self, model, name='Bat 1'):
		#self.prob = Model(name)
		self.name = name
		self.prob = None
		self.batspecs = BatteryDefns[model]

		# Price vector
		self.prices = None                          # Prices as iterable

		# Time attributes
		self.market_time = None                     # Market time implementation (instance of markettime formats)
		self.start_time = None                      # Starting time as datetime.datetime in GMT
		self.year = None                            # Period year
		self.fullmonths = None                      # {mm: (start_idx, end_idx)} Dictionary of FULL months,
													# with the ends on the range index
		self.delta_t = None                         # Time resolution of self.market_time, in numeric hours
													#(whereas self.market_time.delta_t is in datetime.timedelta)

		# dv tables and solution objects
		self.dv_vecs = None                         # DataFrame of Gurobi dv's (rows = len(Prices)+1 for the end point)
		self.__reset_soln()                         # Attrs are described in the method.

		return


	def __reset_soln(self):
		"""Resets solution attributions to None"""
		self.dv_soln = None                         # DataFrame of the dv solution (same shape as self.dv_vecs)
		self.earnings = None                        # Series of battery earnings (same length as self.dv_vecs)
		self.stats = None                           # DataFrame of operational statistcs (see calc_stats())
		return



	def set_prices(self, prices, start_time, market_time):
		"""Sets the prices for the defined period and formulates the optimization model. The time vector is inferred
		from start_time, market_time and the length of prices.

		ARGUMENTS:
			prices          Iterable of input prices.

			start_time      The date+time the prices vector starts. Market time as ("MM/DD/YYYY", hour)
							(e.g. ("01/01/2019", 1) for the first hour in CAISO)

			market_time     A time implementation defined by an instance of one of the standards in markettime.
							Currently, only instances of markettime.CAISO are implemented.

		"""
		if not isinstance(market_time, mt.CAISO):
			raise NotImplementedError("Only markettime.CAISO time implementations are currently supported.")

		self.__reset_soln()

		# ------------------------------------------------------------------- STEP 1: Bind prices and interpret time
		self.prices = prices

		# 1 Market time implementation
		self.market_time = market_time

		# 2 Set GMT start time
		start_dt = mt.datetime.datetime.strptime(start_time[0], '%m/%d/%Y')
		start_time_mkt = market_time.TimeStamp(start_dt, start_time[1])

		self.start_time = market_time.Market_toGMT(start_time_mkt)
		self.year = start_dt.year

		# 3 Detect full months
		batopt.__get_fullmonths(self, start_time_mkt.year)


		# Set duration in numeric hours
		self.delta_t = int(self.market_time.delta_t.seconds / 3600)



		# ------------------------------------------------------------------- STEP 2: Proceed to formulation (default)
		batopt.__formulateprob(self)

		# ------------------------------------------------------------------- REPORT
		# By calculating end_time, we are guaranteeing that we can calculate all time stamps in the period.
		# (potential problem - inferred end is not defined in the DST periods)
		end_time = self.start_time + self.market_time.delta_t*(len(self.prices)-1)
		print("\nPrices set from {} to {}".format(self.market_time.GMT_toMarket(self.start_time),
		                                          self.market_time.GMT_toMarket(end_time)))

		duration = end_time-self.start_time+self.market_time.delta_t
		print("{} D, {} H".format(duration.days, int(duration.seconds / 3600)))

		return


	def solve(self, calc_stats=True):
		"""Solves the optimization problem (battery energy arbitrage). Upon success, extracts the solution and
		calculates the earnings vector."""
		# ------------------------------------------------------------------------------- #
		self.prob.optimize()

		if self.prob.status == 2:
			dv_soln = pd.DataFrame(index=self.dv_vecs.index, columns=self.dv_vecs.columns)

			# Iterate through columns, and exclude final time stamp
			for vtype, ser in self.dv_vecs.iteritems():
				ser = ser.loc[self.dv_vecs.index[0:-1]]
				dv_soln[vtype] = pd.Series(data=[dv.x for dv in ser], index=ser.index)

			# Add final energy
			dv_soln.at[self.dv_vecs.index[-1], 'E'] = self.dv_vecs.at[self.dv_vecs.index[-1], 'E'].x

			# Assert Pch XOR Pdis
			assert all(dv_soln.at[t, 'Pch'] * dv_soln.at[t, 'Pdis'] == 0 for t in dv_soln.index[0:-1])
			# Assert charge neutrality
			assert dv_soln.at[dv_soln.index[0], 'E'] == dv_soln.at[dv_soln.index[-1], 'E']

			# Print revenue
			print("\n\nGenerated revenue of {:0.2f} {} from {} to {}".format(self.prob.objval, options['Currency'],
			                                                                 self.Idx_toMarket(self.dv_vecs.index[0]),
			                                                                 self.Idx_toMarket(self.dv_vecs.index[-2])))


			# ------------------------------------ EXIT ------------------------------------------- #
			# Bind soln
			self.dv_soln = dv_soln
			# Calculate earnings
			self.__calc_earnings()

			if calc_stats: self.calc_stats()

		return


	def calc_stats(self):
		"""Calculates operation statistics, per FULL month and TOTAL (includes partial months).

		STATS:
			Energy Consumed         MWh absorbed from grid
			Energy Released         MWh released to grid
			Energy Lost             MWh energy consumed - energy released

			Energy Revenue          Earnings from discharges
			Energy Costs            Cost from charging
			Net Earning             Energy Revenue - Energy Cost

		"""
		multp = 10**-3 # kWh to MWh conversion

		PricesSer = pd.Series(data=self.prices, index=range(len(self.prices)))

		self.stats = pd.DataFrame(index=[mt.month_abrv[mm] for mm in self.fullmonths]+['Overall'],
		                          columns=['Energy Consumed', 'Energy Released', 'Energy Lost', 'Energy Revenue',
		                                   'Energy Costs', 'Net Earnings'])

		# -------------------------------------------------------------------------------- Step 1: Calc stats
		for mm in {**self.fullmonths, 'Overall':None}:
			try:
				start_idx, end_idx = self.fullmonths[mm]
				mmm = mt.month_abrv[mm]
			except KeyError: # for 'Overall'
				start_idx = 0
				end_idx = len(self.prices)-1
				mmm = mm

			Pch_sub = self.dv_soln.loc[start_idx:end_idx, 'Pch']
			Pdis_sub = self.dv_soln.loc[start_idx:end_idx, 'Pdis']
			Price_sub = PricesSer.loc[start_idx:end_idx]

			# ENERGY
			self.stats.at[mmm, 'Energy Consumed'] = Pch_sub.sum()*self.delta_t*multp
			self.stats.at[mmm, 'Energy Released'] = Pdis_sub.sum()*self.delta_t*multp
			self.stats.at[mmm, 'Energy Lost'] = self.stats.at[mmm, 'Energy Consumed'] - \
			                                    self.stats.at[mmm, 'Energy Released']

			# CASH
			self.stats.at[mmm, 'Energy Revenue'] = round((Price_sub*Pdis_sub).sum()*self.delta_t, 2)
			self.stats.at[mmm, 'Energy Costs'] = round((Price_sub*Pch_sub).sum()*self.delta_t, 2)
			self.stats.at[mmm, 'Net Earnings'] = self.stats.at[mmm, 'Energy Revenue'] - \
			                                     self.stats.at[mmm, 'Energy Costs']
		return


	def plot_24hOperation(self, date):
		"""Plots the battery operation and prices for the given date (as "mmm dd")"""

		# ------------------------------------------------------------------------------------ Get range
		dt = datetime.datetime.strptime(date, "%b %d").replace(year=self.year)

		# Pch, Pdis must be filtered [start_idx, endpt_idx)
		# E         must be filtered [start_idx, endpt_idx]
		start_idx = self.Market_toIdx(self.market_time.TimeStamp(dt, 'first'))
		endpt_idx = start_idx + 1

		# Exit while if endpt_idx points to the next day (or if endpt_idx=len(self.prices)
		while endpt_idx < len(self.prices) and self.Idx_toMarket(endpt_idx).day == dt.day:
			endpt_idx += 1

		# ----------------------------------------------------------------------------------------- PLOT 1: OPERATION
		# ---------------------------------------------------------------------- Main plots
		plt.figure(figsize=(15, 5))
		plt_time = range(start_idx, endpt_idx) # Does NOT contain endpt_idx

		# ------------------------------------------------------------ Main plots
		ax = sns.lineplot(x=range(start_idx, endpt_idx+1), y=self.dv_soln.loc[start_idx:endpt_idx, 'E'],
		                  label='Stored Energy')

		plt.bar(plt_time, -1 * self.dv_soln.loc[start_idx:endpt_idx-1, 'Pch'],
		        align='edge', color="#CB4335", width=1, label='Charge')

		plt.bar(plt_time, self.dv_soln.loc[start_idx:endpt_idx-1, 'Pdis'],
		        align='edge', color="#138D75", width=1, label='Discharge')

		# ------------------------------------------------------------ Formatting
		# Axes labels
		ax.set_xlabel('time', fontsize=13, fontname='arial')
		ax.set_ylabel('Stored energy [kWh] / Output power [kW]', fontsize=13, fontname='arial')

		# Ticks
		xticks = ["H{}".format(str(self.Idx_toMarket(idx).hr).zfill(2)) for idx in plt_time[::2]]
		ax.set_xticks(plt_time[::2])
		ax.set_xticklabels(xticks)
		ax.tick_params(labelsize=12)

		# Title
		ax.set_title("Battery Operation, {}".format(dt.strftime("%b %d")), fontsize=14, fontweight='bold')

		# Misc
		ax.axhline(color="#1B2631", linewidth=0.5)
		ax.set_xlim(plt_time[0], plt_time[-1]+1)
		ax.set_ylim(-self.batspecs['Power [kW]'] * 1.2,
		            self.batspecs['Capacity [kWh]'] + self.batspecs['Power [kW]'])
		ax.legend(loc=1)
		plt.show()
		# ----------------------------------------------------------------------------------------- Report day revenue
		print("Revenue: {} {}".format(round(self.earnings.at[endpt_idx]-self.earnings.at[start_idx], 2),
		                              options['Currency']))

		# ----------------------------------------------------------------------------------------- PLOT 2: PRICES
		plt.figure(figsize=(15, 3))

		# ------------------------------------------------------------ Main plots
		# Note - indexing here is Python (exclusive; up to endpt_idx-1), whereas Pandas is inclusive
		ax = sns.lineplot(x=plt_time, y=np.array(self.prices[start_idx:endpt_idx], dtype='f8') * 1000, color='#616A6B')

		# ------------------------------------------------------------ Formatting
		# Axes labels
		ax.set_xlabel('time', fontsize=13, fontname='arial')
		ax.set_ylabel('Price [{}/MWh]'.format(options['Currency']), fontsize=13, fontname='arial')

		# Ticks
		ax.set_xticks(plt_time[::2])
		ax.set_xticklabels(xticks)
		ax.tick_params(labelsize=12)

		# Title
		ax.set_title("Price Plot", fontsize=14, fontweight='bold')
		# Misc
		ax.set_xlim(plt_time[0], plt_time[-1]+1)
		plt.show()
		return


	def plot_EarningsOverTime(self):
		"""Plots the evolution of net income over the period"""
		plt.figure(figsize=(12, 5))
		ax = sns.lineplot(x=self.earnings.index, y=self.earnings.values)

		# Axes labels
		ax.set_xlabel(self.Idx_toMarket(0).year, fontsize=13, fontname='arial')
		ax.set_ylabel(options['Currency'], fontsize=13, fontname='arial')

		# Axes ticks
		duration = self.market_time.delta_t * len(self.prices)

		if duration.days > 70:
			# Month ticks
			ax.set_xticks([val[0] for key, val in self.fullmonths.items()])
			ax.set_xticklabels([mt.month_abrv[key] for key in self.fullmonths])

		ax.tick_params(labelsize=12)

		# Plot limits
		ax.set_xlim(0, len(self.prices))
		ax.set_ylim(0)

		# Title
		ax.set_title("Earnings over time", fontsize=14, fontweight='bold')

		plt.show()
		return


	def plot_CashFlows(self, plot='RevAndCosts', Summary=False):
		"""Bar plot of revenue vs. costs or net earnings of FULL months (supports 1 yr only)"""
		if self.dv_soln is None:
			raise RuntimeError("No solution. Cannot generate plot at this point.")
		if self.prob.status == 2 and self.stats is None:
			self.calc_stats()

		# ------------------------------------------------------------ Main plots
		if plot not in ('RevAndCosts', 'Net'):
			raise ValueError("Invalid plot choice.")

		plt.figure(figsize=(12, 5))

		Lf = self.stats.index != 'Overall'

		if plot == 'RevAndCosts':
			plt.bar(self.stats.index[Lf], self.stats.loc[Lf, 'Energy Revenue'], color="#CB4335", width=1,
			        label='Energy Rev')
			plt.bar(self.stats.index[Lf], -1 * self.stats.loc[Lf, 'Energy Costs'], color="#F1C40F", width=1,
			        label='Energy Costs')
			plot_title = "Energy Revenues and Costs"
			showLegend = True

		elif plot == 'Net':
			plt.bar(self.stats.index[Lf], self.stats.loc[Lf, 'Net Earnings'], color="#27AE60", width=1)
			plot_title = "Net Earnings"
			showLegend = False

		# ------------------------------------------------------------ Formatting
		ax = plt.gca()
		# Axes labels
		ax.set_xlabel(self.Idx_toMarket(0).year, fontsize=13, fontname='arial')
		ax.set_ylabel(options['Currency'], fontsize=13, fontname='arial')

		# Axes ticks
		ax.set_xticks([val for val in mt.month_abrv.values()])
		ax.tick_params(labelsize=13)

		# xy axes
		ax.axhline(linewidth=1, color='k')

		# Legend
		if showLegend:
			ax.legend(loc=0, fontsize=11)

		# Title
		ax.set_title(plot_title, fontsize=14, fontweight='bold')

		plt.show()

		# --------------------------------------------------------- Summary
		if Summary:
			for key, val in self.stats.loc['Overall', ['Energy Revenue', 'Energy Costs', 'Net Earnings']].iteritems():
				print("{} \t {} {}".format(key, val, options['Currency']))

		if abs(self.stats.loc[Lf, 'Net Earnings'].sum() - self.stats.at['Overall', 'Net Earnings']) > 10 ** -4:
			print("Partial months are not plotted.")
		return


	def plot_monthprices(self, month: str):
		"""Plots an aggregated, 24-hr price profile for the specified month (as mmm)"""
		month_num = mt.month_abrv_rev[month]

		if month_num in [dt.month for dt in self.market_time.DST_periods[self.year]]:
			raise NotImplementedError("The DST switch months are currently not implemented.")
			# Todo - I think the best soln for this is to increment by the day (date.replace)

		# -------------------------------------------------------------------------------------- Step 1: Fetch prices
		try:
			mo_start, mo_end = self.fullmonths[month_num]
		except KeyError:
			raise ValueError("The entered month is not fully covered in the period.")
		Prices_byhr = pd.DataFrame(columns=range(24))  # WIDE-format table (columns as hours)

		for hr in range(24):
			price_thishr = np.array(self.prices[mo_start + hr:mo_end + 1:24], dtype='f8') * 1000
			Prices_byhr[hr] = pd.Series(data=price_thishr, index=range(len(price_thishr)))

		assert Prices_byhr.isnull().sum().sum() == 0

		# -------------------------------------------------------------------------------------- Step 2: Plot
		plt.figure(figsize=(12, 5))
		plt.boxplot([Prices_byhr[hr] for hr in range(24)])
		# ----------------------------------------------
		ax = plt.gca()

		# Axes Title
		ax.set_title("24-hr aggregated prices for {}".format(month), fontsize=13)

		# Axes labels
		ax.set_ylabel("{}/MWh".format(options['Currency']), fontsize=12, fontname='arial')

		# Axes ticks
		ax.tick_params(labelsize=12)

		plt.show()
		return


	def __formulateprob(self):
		"""Formulates the optimization problem."""
		self.prob = Model(self.name)

		# --------------------------------------------------------------------------- STEP 1: Build dvs
		# DV vector table
		self.dv_vecs = pd.DataFrame(index=range(len(self.prices)+1), columns=['E', 'Pch', 'Pdis', 'b'])

		for dv_type in self.dv_vecs.columns:
			self.dv_vecs[dv_type] = batopt.__create_DVvec(self, dv_type)

		# Final charge
		self.dv_vecs.at[self.dv_vecs.index[-1], 'E'] = self.prob.addVar(name="Efin", vtype=GRB.CONTINUOUS, lb=0,
		                                                                ub = self.batspecs.at['Capacity [kWh]'])


		# --------------------------------------------------------------------------- STEP 2: Build constraints
		batopt.__all_constrs(self)

		# --------------------------------------------------------------------------- STEP 3: Set objective
		Obj = LinExpr()

		for idx, Price in enumerate(self.prices):
			Pch  = self.dv_vecs.at[idx, 'Pch']
			Pdis = self.dv_vecs.at[idx, 'Pdis']

			Obj.addTerms([Price * self.delta_t, -Price * self.delta_t], [Pdis, Pch])

		self.prob.setObjective(Obj, sense=GRB.MAXIMIZE)

		# --------------------------------------------------------------------------- STEP 4: Report
		self.prob.update()
		print("\nProblem formulated")
		print(self.prob)

		return


	def __create_DVvec(self, dv_type):
		"""Creates the vector optimization variables for the given model, and returns it as a series (same length as
		self.prices).

		ARGUMENTS
			dv_type:    'E'     self charge
						'Pch'   charging power
						'Pdis'  discharging power
						'b'     charge/discharge decision

		RETURNS
			Pandas Series of the requested decision variables.

		This follows the form in MA.
		"""
		batspecs = self.batspecs
		#time_axis = self.prices.index
		prms = {}
		# --------------------------------------------------------------------------------- STEP 1 Define dv attributes
		if dv_type == 'E':
			prms["vtype"] = GRB.CONTINUOUS
			prms["ub"] = batspecs.at['Capacity [kWh]']
			prms["lb"] = batspecs.at['Capacity [kWh]'] * (1 - batspecs.at['DoD [%]'] / 100)

		elif dv_type == 'Pch' or dv_type == 'Pdis':
			prms["vtype"] = GRB.CONTINUOUS
			prms["ub"] = batspecs.at['Power [kW]']
			prms["lb"] = 0

		elif dv_type == 'b':
			prms["vtype"] = GRB.BINARY
			prms["ub"] = 1
			prms["lb"] = 0

		else:
			raise ValueError("Undefined var type.")

		# --------------------------------------------------------------------------------- STEP 2 Define dv
		assert all(attr in prms for attr in ("vtype", "lb", "ub"))
		# Apart from requiring an explicit parameter setting, this assertion ensures proper control flow in the body.
		return pd.Series(data=[self.prob.addVar(name="{}, {}".format(dv_type, idx), **prms)
		                       for idx in range(len(self.prices))], dtype="object")


	def __all_constrs(self):
		"""
		Applies the ff. constraints to the model:
			- battery charge balance (linear)
			- Pch XOR Pdis (2x linear)
			- Final charge = starting charge (linear)

		ARGUMENTS
			model:      Gurobi model
			dv_vecs:    DataFrame of all vector decision variables (E, Pch, Pdis, b)
			dv_Efin:    Final battery charge dv

		RETURNS:
			None
		"""
		# ------------------------------------------------------------------- Step 0 Prelims
		# Battery specs
		Pmax = self.batspecs.at['Power [kW]']
		eff_ch = (self.batspecs.at['Cycle Efficiency [%]']/100)**0.5
		eff_dis = eff_ch

		# Updated -- loops only until the 2nd to the last timestamp
		for idx, t in enumerate(self.dv_vecs.index[0:-1]):
			# -------------------------------------------------------------- Step 1 Fetch dvs for time t
			Et   = self.dv_vecs.at[t, 'E']
			Et_next = self.dv_vecs.at[self.dv_vecs.index[idx + 1], 'E']
			Pch  = self.dv_vecs.at[t, 'Pch']
			Pdis = self.dv_vecs.at[t, 'Pdis']
			b    = self.dv_vecs.at[t, 'b']

			# -------------------------------------------------- a) Charge Balance
			self.prob.addLConstr(Et_next == Et + (eff_ch*Pch - Pdis/eff_dis)*self.delta_t,
			                 name="(ChBal,{})".format(idx))

			# -------------------------------------------------- b) Pch and binary
			self.prob.addLConstr(Pch/Pmax + (1-b) <= 1,
			                 name="(PchBin,{})".format(idx))

			# -------------------------------------------------- c) Pdis and binary
			self.prob.addLConstr(Pdis / Pmax + b <= 1,
			                 name="(PdisBin,{})".format(idx))

		# Not part of loop!
		# --------------------------------------- d) Final charge = starting charge
		Estart = self.dv_vecs.at[self.dv_vecs.index[0], 'E']
		Efin   = self.dv_vecs.at[self.dv_vecs.index[-1], 'E']
		self.prob.addLConstr(Efin == Estart, name="Charge Neutral")

		return


	def __calc_earnings(self):
		"""Calculates self.earnings post-solution."""
		self.earnings = pd.Series(data=0.0, index=self.dv_vecs.index, dtype='f8')

		for idx in range(len(self.prices)):
			price = self.prices[idx]
			Pch = self.dv_soln.at[idx, 'Pch']
			Pdis = self.dv_soln.at[idx, 'Pdis']

			self.earnings.iat[idx+1] = self.earnings.iat[idx] + price*(Pdis-Pch)*self.delta_t


		assert abs(self.earnings.iat[-1] - self.prob.objval) < 10 ** -6

		return


	def __get_fullmonths(self, start_TimeStamp_year):
		"""Sets the self.fullmonths attribute"""
		self.fullmonths = {}

		# {mm: (start, end)}, with start, end as market TimeStamp
		for mm, val in self.market_time.get_month_ends(start_TimeStamp_year).items():
			start_mkt, end_mkt = val

			try:
				start_idx = self.Market_toIdx(start_mkt)
			except OutsideTimeRange:
				continue

			try:
				end_idx = self.Market_toIdx(end_mkt)
			except OutsideTimeRange:
				continue

			self.fullmonths[mm] = (start_idx, end_idx)

		return


	def Market_toIdx(self, markettime):
		"""Converts TimeStamp instances of self.market_time into the corresponding index along the range index."""
		GMT = self.market_time.Market_toGMT(markettime)
		idx = (GMT-self.start_time)/self.market_time.delta_t

		if idx.is_integer():
			idx = int(idx)
		else:
			raise ValueError("The passed TimeStamp led to a non-integer period offset from the start time.")

		if not (0 <= idx < len(self.prices)):
			raise OutsideTimeRange("The passed TimeStamp is outside the time range of the price vector.")

		return idx


	def Idx_toMarket(self, idx: int):
		"""Converts an index within the range index into the corresponding TimeStamp."""
		if isinstance(idx, float) and not idx.is_integer():
			raise TypeError("Pls. pass an integer (within the range index).")

		if not (0 <= idx < len(self.prices)):
			raise ValueError("Passed index is outside the range of [0,{}]".format(len(self.prices)-1))

		GMT = self.start_time + idx*self.market_time.delta_t

		return self.market_time.GMT_toMarket(GMT)


class batoptError(Exception):
	"""Base exception for batopt"""
	pass


class OutsideTimeRange(batoptError):
	"""Raised when the market time stamp passed to (batopt).Market_toIdx() is outside the concerned period."""
	pass


def simple_payback(Rev_energy, Rev_AS, Cost_energy, Battery_kWh, i=0.05, USD_perkWh = 180, percent_storage_costs=80):
	"""Simple cashflow calculation to compute the payback period (i.e. whole years until project has a positive net
	value.

	Assumptions:
		Principal = Battery_kWh * USD_perkWh * (100/percent_storage_costs)

		Yearly Maintenance Cost = 0 -- the only cost is the cost of charging the battery

		Yearly revenues and costs are fixed.

		Interest rate is fixed.

	Battery Cash Flow:
		Yearly Income = Rev_energy + Rev_AS - Cost_energy

		Rev_energy      Yearly revenue from energy arbitrage
		Rev_AS          Yearly revenue from all ancillary services (for simplicity, express as a multiple of Rev_energy)


	Returns:
		Numpy array tracking the net present value, until the year the present value becomes positive. The payback
		period is one less the length of this array.

	"""
	YearlyIncome = Rev_energy + Rev_AS - Cost_energy

	Principal = Battery_kWh * USD_perkWh * (100 / percent_storage_costs)

	if i * Principal > YearlyIncome:
		raise RuntimeError("The yearly income cannot cover the cost of capital.")

	Account = np.array([-Principal], dtype='f8')

	for yr in range(50):
		if Account[yr] >= 0:
			break
		Account = np.append(Account, round(Account[yr] * (1 + i) + YearlyIncome, 2))
		yr += 1
	else:
		raise RuntimeError("Project did not break-even in {} years".format(yr))

	print("Payback period: {} yrs".format(yr))

	return Account