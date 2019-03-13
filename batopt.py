import pandas as pd
from gurobipy import *

import matplotlib.pyplot as plt
import seaborn as sns
sns.set_style("whitegrid")

def create_DVs(model, dv_type, time_vec, BatteryModel, BatteryDefns):
	"""Creates the vector optimization variables for the given model, and returns it as a series.

	ARGUMENTS
		model:      Gurobi model
		dv_type:    'E'     battery charge
					'Pch'   charging power
					'Pdis'  discharging power
					'b'     charge/discharge decision
		time_vec:   The time vector (index of the vector)

		BatteryModel:   The battery model (one of the columns of BatteryDefns)
		BatteryDefns:   The battery specs table

	RETURNS
		Pandas Series of the requested decision variables.

	This follows the form in MA.
	"""
	dv_name = lambda dv_type, t: "({}, {}:{})".format(dv_type, str(t.hour).zfill(2), str(t.minute).zfill(2))
	prms = {}
	# --------------------------------------------------------------------------------- STEP 1 Define dv attributes
	if dv_type == 'E':
		prms["vtype"] = GRB.CONTINUOUS
		prms["ub"] = BatteryDefns.at['Capacity [kWh]', BatteryModel]
		prms["lb"] = prms["ub"]*(1-BatteryDefns.at['DoD [%]', BatteryModel]/100)

	elif dv_type == 'Pch' or dv_type == 'Pdis':
		prms["vtype"] = GRB.CONTINUOUS
		prms["ub"] = BatteryDefns.at['Power [kW]', BatteryModel]
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
	return pd.Series(data=[model.addVar(name=dv_name(dv_type, t), **prms) for t in time_vec],
	                 index=time_vec, dtype="object")



def all_constrs(model, dv_vecs, dv_Efin, BatteryModel, BatteryDefns):
	"""Applies the ff. constraints to the model:
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
	# Time delta
	delta_t = (dv_vecs.index[1]-dv_vecs.index[0]).seconds/3600

	# Battery specs
	Pmax = BatteryDefns.at['Power [kW]', BatteryModel]
	eff_ch = (BatteryDefns.at['Cycle Efficiency [%]', BatteryModel] / 100) ** 0.5
	eff_dis = eff_ch

	HHMM = lambda t: "{}:{}".format(str(t.hour).zfill(2), str(t.minute).zfill(2))


	for idx, t in enumerate(dv_vecs.index):
		# -------------------------------------------------------------- Step 1 Fetch dvs for time t
		Et   = dv_vecs.at[t, 'E']
		Pch  = dv_vecs.at[t, 'Pch']
		Pdis = dv_vecs.at[t, 'Pdis']
		b    = dv_vecs.at[t, 'b']

		try:
			Et_next = dv_vecs.at[dv_vecs.index[idx + 1], 'E']
		except IndexError:
			Et_next = dv_Efin


		# -------------------------------------------------- a) Charge Balance
		model.addLConstr(Et_next == Et + (eff_ch*Pch - Pdis/eff_dis)*delta_t,
		                 name="(ChBal,{})".format(HHMM(t)))

		# -------------------------------------------------- b) Pch and binary
		model.addLConstr(Pch/Pmax + (1-b) <= 1,
		                 name="(PchBin,{})".format(HHMM(t)))

		# -------------------------------------------------- c) Pdis and binary
		model.addLConstr(Pdis / Pmax + b <= 1,
		                 name="(PdisBin,{})".format(HHMM(t)))


	# -------------------------------------------------- d) Final charge = starting charge
	Estart = dv_vecs.at[dv_vecs.index[0], 'E']
	model.addLConstr(dv_Efin == Estart,
	                 name="Charge Neutral")

	return


def setObj(model, dv_vecs, Prices):
	"""Sets the objective, given the prices."""
	# Time delta
	delta_t = (dv_vecs.index[1] - dv_vecs.index[0]).seconds / 3600

	Obj = LinExpr()

	for idx, t in enumerate(dv_vecs.index):
		Price = Prices.iat[idx]
		Pch   = dv_vecs.at[t, 'Pch']
		Pdis  = dv_vecs.at[t, 'Pdis']

		Obj.addTerms([Price*delta_t, -Price*delta_t], [Pdis, Pch])

	model.setObjective(Obj, sense=GRB.MAXIMIZE)
	return


def solve(model, dv_vecs, dv_Efin):
	"""Solves the model, and if successful, extracts the solution. The solution table is of the same format as the
	decision variable table, except an extra row to include the end charge level (with all other dvs as nans)"""
	model.optimize()

	if model.status == 2:
		t_delta = dv_vecs.index[1] - dv_vecs.index[0]

		dv_soln = pd.DataFrame(index=dv_vecs.index, columns=dv_vecs.columns)

		for vtype, ser in dv_vecs.iteritems():
			dv_soln[vtype] = pd.Series(data=[dv.x for dv in ser], index=dv_vecs.index)

		# Add final energy
		dv_soln.at[dv_vecs.index[23]+t_delta, 'E'] = dv_Efin.x

		# Assert Pch XOR Pdis
		assert all(dv_vecs.at[t, 'Pch'].x * dv_vecs.at[t, 'Pdis'].x == 0 for t in dv_vecs.index)
		# Assert charge neutrality
		assert dv_vecs['E'].iat[0].x == dv_Efin.x

		# Print revenue
		print("\n\nGenerated revenue of {:0.2f} Euros from {} to {}".format(model.objval, dv_vecs.index[0],
		                                                                   dv_vecs.index[-1]+t_delta))

		return dv_soln


def plot_batop(model, dv_soln):
	"""Plots the battery operation over the period (24h)."""
	plt_time = range(25)
	# ------------------------------------------------------------------------------------------------------ BATTERY OPERATION
	plt.figure(figsize=(15, 6))

	# ------------------------------------------------------------ Main plots
	ax = sns.lineplot(x=plt_time, y=dv_soln['E'], label='Stored Energy')
	plt.bar(plt_time, -1 * dv_soln['Pch'], align='edge', color="#CB4335", width=1, label='Charge')
	plt.bar(plt_time, dv_soln['Pdis'].tolist(), align='edge', color="#138D75", width=1, label='Discharge')

	# ------------------------------------------------------------ Formatting
	# Axes labels
	ax.set_xlabel('time', fontsize=13, fontname='arial')
	ax.set_ylabel('Stored energy [kWh] / Output power [kW]', fontsize=13, fontname='arial')

	# Ticks
	xticks = range(0, 24, 2)
	xticklabels = ["{}:00".format(str(t).zfill(2)) for t in xticks]
	ax.set_xticks(xticks)
	ax.set_xticklabels(xticklabels, fontsize=12)

	yticks = range(-50, 250, 50)
	ax.set_yticks(yticks)
	ax.set_yticklabels(yticks, fontsize=12)

	# Title
	ax.set_title("Battery Operation", fontsize=15, fontweight='bold')

	# Misc
	ax.axhline(color="#1B2631", linewidth=0.5)
	ax.set_xlim(plt_time[0], plt_time[-1])
	ax.set_ylim(-70, 250)
	plt.gca().legend(loc=1)


	plt.show()
	print("Generated revenue of {:0.2f} Euros \nfrom {} to {}".format(model.objval, dv_soln.index[0],
	                                                                      dv_soln.index[-1]))


def plot_prices(Prices):
	"""Plots prices to compare with battery operation (24h)"""
	plt.figure(figsize=(15, 3))
	plt_time = range(24)

	# ------------------------------------------------------------ Main plots
	ax = sns.lineplot(x=plt_time, y=Prices, color='#616A6B')

	# ------------------------------------------------------------ Formatting
	# Axes labels
	ax.set_xlabel('time', fontsize=13, fontname='arial')
	ax.set_ylabel('Price [Euro/kWh]', fontsize=13, fontname='arial')

	# Ticks
	xticks = range(0, 24, 2)
	xticklabels = ["{}:00".format(str(t).zfill(2)) for t in xticks]
	ax.set_xticks(xticks)
	ax.set_xticklabels(xticklabels, fontsize=12)

	# Title
	ax.set_title("Price Plot", fontsize=14)
	# Misc
	ax.set_xlim(plt_time[0], plt_time[-1])
	plt.show()