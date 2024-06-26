from __future__ import absolute_import, division, print_function
import cplex
import pandas as pd
from Solution import Solution
import time
import numpy as np
import math
from Constants import Constants
from Tool import Tool
from ScenarioTreeNode import ScenarioTreeNode
from DecentralizedMRP import DecentralizedMRP


import itertools
class MIPSolver(object):
    M = cplex.infinity

    # constructor
    def __init__(self,
                 instance,
                 model,
                 scenariotree,
                 evpi=False,
                 implicitnonanticipativity=True,
                 givenquantities=[],
                 givensetups=[],
                 givenconsumption=[],
                 fixsolutionuntil=-1,
                 evaluatesolution=False,
                 yfixheuristic=False,
                 demandknownuntil=-1,
                 mipsetting="",
                 warmstart=False,
                 usesafetystock=False,
                 usesafetystockgrave=False,
                 rollinghorizon=False,
                 expandfirstnode = False, #expandfirstnode is used to remove the non anticipativity constraint, if used, variable of the rootnode of the tree are created for each scenario
                 logfile="result", # revise error
                 givenSGrave=[]):

        # Define some attributes and functions which help to set the index of the variable.
        # the attributs nrquantiyvariables, nrinventoryvariable, nrproductionvariable, and nrbackordervariable gives the number
        # of variable of each type
        self.NrQuantityVariables = 0
        self.NrConsumptionVariables = 0
        self.NrInventoryVariable = 0
        self.NrProductionVariable = 0
        self.NrBackorderVariable = 0

        # The variable startquantityvariable, startinventoryvariable, startprodustionvariable, and startbackordervariable gives
        # the index at which each variable type start
        self.StartQuantityVariable = 0
        self.StartConsumptionVariable = 0
        self.StartInventoryVariable = 0
        self.StartProductionVariable = 0
        self.StartBackorderVariable = 0

        self.Instance = instance
        #Takes value in _Fix, Y_Fix, YQFix
        self.Model = model
        #If non anticipativity constraints are added, they can be implicit or explicit.
        self.UseImplicitNonAnticipativity = implicitnonanticipativity
        #self.UseNonAnticipativity
        self.EVPI = evpi
        self.MipSetting = mipsetting
        #The set of scenarios used to solve the instance
        self.DemandScenarioTree = scenariotree
        self.DemandScenarioTree.Owner = self
        self.NrScenario = len([n for n in self.DemandScenarioTree.Nodes if len(n.Branches) == 0])
        # DemandKnownUntil is used for the YQFix model, when the first period are considered known.
        self.DemandKnownUntil = demandknownuntil
        self.YFixHeuristic= yfixheuristic
        self.UseSafetyStock = usesafetystock
        self.UseSafetyStockGrave = usesafetystockgrave
        self.ExpendFirstNode = expandfirstnode
        self.ComputeIndices()

        self.Scenarios = scenariotree.GetAllScenarios(True, expandfirstnode)

        self.GivenQuantity = givenquantities

        self.GivenSetup = givensetups
        self.GivenConsumption = givenconsumption
        self.FixSolutionUntil = fixsolutionuntil
        self.WamStart = warmstart

        self.ScenarioSet = range(self.NrScenario)
        self.Cplex = cplex.Cplex()

        self.EvaluateSolution = evaluatesolution
        self.logfilename= logfile
        #This list is filled after the resolution of the MIP
        self.SolveInfo = []

        #This list will contain the set of constraint number for each flow constraint
        self.FlowConstraintNR = []
        self.BigMConstraintNR = []

        self.QuantityConstraintNR = []
        self.SetupConstraint = []
        self.RollingHorizon = rollinghorizon
        self.GivenSSGrave = givenSGrave


    # Compute the start of index and the number of variables for the considered instance
    def ComputeIndices(self):

        self.NrProductionVariable = self.Instance.NrProduct * self.Instance.NrTimeBucket

        if self.Model == Constants.ModelYFix:
            if self.ExpendFirstNode :
                self.NrProductionVariable = self.Instance.NrProduct * self.Instance.NrTimeBucket * self.NrScenario
                self.NrQuantityVariables = self.Instance.NrProduct * self.Instance.NrTimeBucket * self.NrScenario
                self.NrConsumptionVariables = len(self.Instance.ConsumptionSet) \
                                              * self.Instance.NrTimeBucket * self.NrScenario
                                            # sum(self.Instance.NrComponent[p] for p in self.Instance.ProductSet) \

            else:
                self.NrQuantityVariables = self.Instance.NrProduct * (self.DemandScenarioTree.NrNode - 1 - self.NrScenario)

                self.NrConsumptionVariables = len(self.Instance.ConsumptionSet) \
                                              * (self.DemandScenarioTree.NrNode - 1 - self.NrScenario)
                # sum(self.Instance.NrComponent[p] for p in self.Instance.ProductSet)  \


        else:
            self.NrQuantityVariables = self.Instance.NrProduct * self.Instance.NrTimeBucket
            self.NrConsumptionVariables = len(self.Instance.ConsumptionSet) \
                                          * self.Instance.NrTimeBucket
            # sum(self.Instance.NrComponent[p] for p in self.Instance.ProductSet)  \

        # There is no decision regarding inventories at node 1
        nodeproductafterfirstperiod = self.Instance.NrProduct * (self.DemandScenarioTree.NrNode - 2)
        self.NrInventoryVariable = nodeproductafterfirstperiod

        self.NrBackorderVariable = len(self.Instance.ProductWithExternalDemand) * (self.DemandScenarioTree.NrNode - 2)

        self.StartQuantityVariable = 0
        self.StartConsumptionVariable = self.StartQuantityVariable + self.NrQuantityVariables
        self.StartInventoryVariable = self.StartConsumptionVariable + self.NrConsumptionVariables
        self.StartProductionVariable = self.StartInventoryVariable + self.NrInventoryVariable
        self.StartBackorderVariable = self.StartProductionVariable + self.NrProductionVariable
        self.NrFixedQuantity = 0
        self.NrHasLeftOver = 0



    def GetSenarioIndexForQuantity(self, p, t, w):
        if self.Model == Constants.ModelYQFix:
            return 0
        else:
            return self.Scenarios[w].QuanitityVariable[t][p]

    def GetSenarioIndexForConsumption(self, p, q, t, w):
        if self.Model == Constants.ModelYQFix:
            return 0
        else:
            return self.Scenarios[w].ConsumptionVariable[t][p][q]

    # This function returns the name of the quantity variable for product p and time t
    def GetNameQuantityVariable(self, p, t, w):
        scenarioindex = self.GetSenarioIndexForQuantity(p, t, w)
        return "q_p_t_s_%d_%d_%d" % (p, t, scenarioindex)

    # This function returns the name of the quantity variable for product p and time t
    def GetNameConsumptionVariable(self, p, q,  t, w):
        scenarioindex = self.GetSenarioIndexForConsumption(p, q, t, w)
        return "w_p_q_t_s_%d_%d_%d_%d" % (p, q, t, scenarioindex)

    # This function returns the name of the inventory variable for product p and time t
    def GetNameInventoryVariable(self, p, t, w):
        scenarioindex = self.Scenarios[w].InventoryVariable[t][p]
        return "i_%d_%d_%d" % (p, t, scenarioindex)

    def GetNameIndexLetOver(self, p, t, w):
        return "L_%d_%d_%d" % (p, t, w)

    def GetNameFixedQuantity(self, p, t):
        return "Qb_%d_%d" % (p, t)

    # This function returns the name of the production variable for product p and time t
    def GetNameProductionVariable(self, p, t, w=0):
        return "p_%d_%d_%d" % (p, t, w)

    # This function returns the name of the backorder variable for product p and time t
    def GetNameBackOrderQuantity(self, p, t, w):
        scenarioindex = self.Scenarios[w].BackOrderVariable[t][self.Instance.ProductWithExternalDemandIndex[p]]
        return "b_%d_%d_%d" % (p, t, scenarioindex)

    # This function returns the name of the backorder variable for product p and time t
    def GetNameStartingInventory(self, p, t):
        return "starting_inventory_%d_%d"%(p,t)

    # This function returns the name of the backorder variable for product p and time t
    def GetNameSVariable(self, p, t):
        return "Big_S_%d_%d"%(p, t)

    # the function GetIndexQuantityVariable returns the index of the variable Q_{p, t}. Quantity of product p produced at time t
    def GetIndexQuantityVariable( self, p, t, w):
        #Defined in the subclasses
        if self.Model == Constants.ModelYQFix:
            return self.GetStartQuantityVariable() + t * self.Instance.NrProduct + p
        else:
            return self.Scenarios[w].QuanitityVariable[t][p]

    # the function GetIndexQuantityVariable returns the index of the variable Q_{p, t}. Quantity of product p produced at time t
    def GetIndexConsumptionVariable(self, p, q, t, w):

        if not self.Instance.Alternates[p][q]:
            raise NameError(" there is no component %s -> %s "%(q,p))
        # Defined in the subclasses
        if self.Model == Constants.ModelYQFix:
            return self.GetStartConsumptionVariable() \
                   + t * self.Instance.NrAlternateTotal \
                   + sum(self.Instance.NrAlternate[k] for k in range(p)) \
                   + sum(self.Instance.Alternates[p][k] for k in range(q+1))\
                    -1
        else:
            return self.Scenarios[w].ConsumptionVariable[t][p][q]

    # the function GetIndexInventoryVariable returns the index of the variable I_{p, t}. Inventory of product p produced at time t
    def GetIndexInventoryVariable(self, p, t, w):
        return self.Scenarios[w].InventoryVariable[t][p]

    # the function GetIndexProductionVariable returns the index of the variable Y_{p, t, w}.
    # This variable equal to one is product p is produced at time t, 0 otherwise
    def GetIndexProductionVariable(self, p, t, w):
        if self.ExpendFirstNode:
            return self.GetStartProductionVariable() + w * self.Instance.NrProduct * self.Instance.NrTimeBucket + t * self.Instance.NrProduct + p
        return self.GetStartProductionVariable() + t * self.Instance.NrProduct + p

    # the function GetIndexBackorderVariable returns the index of the variable B_{p, t}. Quantity of product p produced backordered at time t
    def GetIndexBackorderVariable( self, p, t, w):
        return self.Scenarios[w].BackOrderVariable[t][self.Instance.ProductWithExternalDemandIndex[p]];

    # the function GetIndexQuantityVariable returns the index of the variable Q_{p, t}. Quantity of product p produced at time t
    def GetIndexSVariable(self, p, t):
        return self.StartSVariable + t * self.Instance.NrProduct + p

    def GetIndexFixedQuantity(self, p, t):
        return self.GetStartFixedQuantityVariable() + t * self.Instance.NrProduct + p

    def GetIndexHasLeftover(self, p, t, w):
        return self.GetStartHasLeftOver() + w * self.Instance.NrTimeBucket * self.Instance.NrProduct + t * self.Instance.NrProduct + p

    # the function GetIndexQuantityVariable returns the index of the variable S_{p, t}. S level of product p produced at time t
    def GetIndexSVariable(self, p, t):
        return self.StartSVariable + t * self.Instance.NrProduct + p

     # This function return the index of the variable known demand. They are ordered by product (only for products wiht external demands)
    def GetIndexSafetystockPenalty(self, p, t):
        return self.GetStartSafetystockPenalty() + t * self.Instance.NrProduct + p

    #This function return the index of the variable known demand. They are ordered by product (only for products wiht external demands)
    def GetIndexKnownDemand(self, p):
        return self.GetStartKnownDemand() + self.Instance.ProductWithExternalDemandIndex[p]

    #This function return the index of the variable initial inventory (which should not be used with knowndemand)
    def GetIndexInitialInventoryInRollingHorizon(self, p, t):
        if self.DemandKnownUntil >= 0:
            raise NameError("The intial inventory cannot be used with known demande")

        return self.GetStartKnownDemand() + t * self.Instance.NrProduct + p

    def GetStartKnownDemand(self):
        nrpenalti = 0
        if self.UseSafetyStockGrave:
            nrpenalti = self.Instance.NrProduct * self.Instance.NrTimeBucket

        return self.GetStartSafetystockPenalty() + nrpenalti

    def GetStartSafetystockPenalty(self):
        return self.StartBackorderVariable + self.NrBackorderVariable

    #return the index at which the backorder variables starts
    def GetStartBackorderVariable(self):
        return self.StartBackorderVariable

    #return the index at which the production variables starts
    def GetStartProductionVariable(self):
        return self.StartProductionVariable

    #retunr the index at which the inventory variables starts
    def GetStartInventoryVariable(self):
        return self.StartInventoryVariable

    #return the index at which the quantity variable starts
    def GetStartQuantityVariable(self):
        return self.StartQuantityVariable

    # return the index at which the quantity variable starts
    def GetStartConsumptionVariable(self):
        return self.StartConsumptionVariable

    #return the number of production variables
    def GetNrProductionVariable(self):
        return self.NrProductionVariable

    # return the number of inventory variables
    def GetNrInventoryVariable(self):
        return self.NrInventoryVariable

    def GetQuantityCoeff(self, p,t,w):
        return (self.Instance.VariableCost[p]
                 * self.Scenarios[w].Probability) \
                 * (np.power(self.Instance.Gamma, t))

    def GetConsumptionCoeff(self, p, q, t, w):

        cost = self.Instance.GetComsumptionCost(p,q)

        return (cost
            * self.Scenarios[w].Probability) \
            * (np.power(self.Instance.Gamma, t))

    def GetProductionCefficient(self, p, t, w):
        return self.Instance.SetupCosts[p] \
                * sum(self.Scenarios[w].Probability for w in self.ScenarioSet) \
                * np.power(self.Instance.Gamma, t)

    # This function define the variables
    def CreateVariable(self):

        if self.UseSafetyStockGrave:
            decentralized = DecentralizedMRP(self.Instance, self.UseSafetyStockGrave)

            if len(self.GivenSSGrave) > 0:
                self.GivenSSGrave = decentralized.ComputeSafetyStockGrave()

        # Define the cost vector for each variable. As the numbber of variable changes when non anticipativity is used the cost are created differently
        variableproductioncosts = [0] * self.NrQuantityVariables
        inventorycosts = [0] * self.NrInventoryVariable
        setupcosts = [0] * self.NrProductionVariable
        backordercosts = [0] * self.NrBackorderVariable
        conumptioncost = [0] * self.NrConsumptionVariables
        for w in self.ScenarioSet:
            for t in self.Instance.TimeBucketSet:
                for p in self.Instance.ProductSet:
                    # Add the cost of the variable representing multiple scenarios
                    inventorycostindex = self.Scenarios[w].InventoryVariable[t][p] - self.StartInventoryVariable
                    inventorycosts[inventorycostindex] = inventorycosts[inventorycostindex] \
                                                         + self.Instance.InventoryCosts[p] \
                                                           * self.Scenarios[w].Probability \
                                                           * np.power(self.Instance.Gamma, t)

                    # Add the cost of the variable representing multiple scenarios
                    quantityindex = self.GetIndexQuantityVariable(p, t, w) - self.StartQuantityVariable
                    variableproductioncosts[quantityindex] = variableproductioncosts[quantityindex] \
                                                            + self.GetQuantityCoeff(p, t, w)



                    if self.Instance.HasExternalDemand[p]:
                        backordercostindex = self.Scenarios[w].BackOrderVariable[t][
                                                 self.Instance.ProductWithExternalDemandIndex[p]] - self.StartBackorderVariable
                        if t < self.Instance.NrTimeBucket -1:
                            backordercosts[backordercostindex] = backordercosts[backordercostindex] \
                                                                 + self.Instance.BackorderCosts[p] \
                                                                   * self.Scenarios[w].Probability \
                                                                   * np.power(self.Instance.Gamma, t)
                        else: backordercosts[backordercostindex] = backordercosts[backordercostindex] \
                                                                   + self.Instance.LostSaleCost[p] \
                                                                   * self.Scenarios[w].Probability \
                                                                   *np.power(self.Instance.Gamma, t)
                for c in self.Instance.ConsumptionSet:
                        consumptionindex = self.GetIndexConsumptionVariable(c[0], c[1], t,
                                                                            w) - self.StartConsumptionVariable

                        conumptioncost[consumptionindex] = conumptioncost[consumptionindex] \
                                                           + self.GetConsumptionCoeff(c[0], c[1], t, w)


        setupcosts = [self.GetProductionCefficient(p,t,w)
                      for t in self.Instance.TimeBucketSet for p in self.Instance.ProductSet]


        if self.ExpendFirstNode:
            setupcosts = [0]*self.NrProductionVariable
            for w in self.ScenarioSet:
                for t in self.Instance.TimeBucketSet:
                    for p in self.Instance.ProductSet:
                        # Add the cost of the variable representing multiple scenarios
                        setupcostindex = self.Scenarios[w].ProductionVariable[t][p] - self.StartProductionVariable
                        setupcosts[setupcostindex] =  self.Instance.SetupCosts[p] \
                                                           * self.Scenarios[w].Probability  \
                                                           * np.power(self.Instance.Gamma, t)
        # the variable quantity_prod_time_scenario_p_t_w indicated the quantity of product p produced at time t in scneario w
        upperbound = [self.M] * self.NrQuantityVariables
        if len(self.GivenSetup) > 0 and (self.EvaluateSolution or self.YFixHeuristic):
            for w in self.ScenarioSet:
                for t in self.Instance.TimeBucketSet:
                    for p in self.Instance.ProductSet:
                        #round the setup when not evaluating to avoid cases where Q can take non 0 values / when evaluating, the previous rounding error ust remain valid but bigM should not change
                        setup = self.GivenSetup[t][p]

                        if (not self.EvaluateSolution) and self.YFixHeuristic:
                            setup = round(self.GivenSetup[t][p], 2)
                        upperbound[self.GetIndexQuantityVariable(p,t,w)] = max(setup * self.M, 0.0)


        self.Cplex.variables.add(obj= variableproductioncosts,
                                 lb=[0.0] * self.NrQuantityVariables,
                                 ub=upperbound)

        upperbound = [self.M] * self.NrConsumptionVariables
        self.Cplex.variables.add(obj=conumptioncost,
                                 lb=[0.0] * self.NrConsumptionVariables,
                                 ub=upperbound)


        # the variable inventory_prod_time_scenario_p_t_w indicated the inventory level of product p at time t in scneario w
        self.Cplex.variables.add(obj=inventorycosts,
                                lb=[0.0] * self.NrInventoryVariable,
                                ub=[self.M] * self.NrInventoryVariable)

        # the variable production_prod_time_scenario_p_t_w equals 1 if a lot of product p is produced at time t in scneario w
        if self.EvaluateSolution or self.YFixHeuristic:
            self.Cplex.variables.add(obj= setupcosts,
                                     lb=[0.0] * self.NrProductionVariable,
                                     ub=[1.0] * self.NrProductionVariable)
        else:
            self.Cplex.variables.add(obj=setupcosts,
                                     types= ['B']*self.NrProductionVariable)

        # the variable backorder_prod_time_scenario_p_t_w gives the amount of product p backordered at time t in scneario w
        self.Cplex.variables.add( obj=backordercosts, #
                                  #[0.0] * nrbackordervariable,
                                  lb=[0.0] * self.NrBackorderVariable,
                                  ub=[self.M] * self.NrBackorderVariable)

        timetoenditem = self.Instance.GetTimeToEnd()
        if self.UseSafetyStockGrave:
            nrsvariable = len(self.Instance.ProductSet) * self.Instance.NrTimeBucket
            penalty =[1.5 * self.Instance.InventoryCosts[p]
                      if (t + timetoenditem[p] < self.Instance.NrTimeBucket - 1)
                      else
                      5 * self.Instance.InventoryCosts[p]
                      for t in self.Instance.TimeBucketSet for p in self.Instance.ProductSet]
            self.Cplex.variables.add(obj=penalty,
                                     lb=[0.0] * nrsvariable,
                                     ub=[self.M] * nrsvariable)

        #Add a variable which represents the known demand:
        if self.DemandKnownUntil >= 0:
            nrknowndemand = len( self.Instance.ProductWithExternalDemand )
            value = [ sum( self.Scenarios[0].Demands[tau][p] for tau in range(self.DemandKnownUntil ))  for p in self.Instance.ProductWithExternalDemand ]
            if Constants.Debug:
                print("KnownDemandValue:%r - %r"%(value, self.DemandKnownUntil))
            self.Cplex.variables.add(obj=[0.0] * nrknowndemand,
                                     lb=value,
                                     ub=value)
        if self.RollingHorizon:
            #starting inventory used in rolling horizon framework.
            self.Cplex.variables.add(obj=[0.0] * ((len(self.Instance.ProductSet)  * max(self.Instance.MaimumLeadTime, 1))),
                                     lb=[0.0] * ((len(self.Instance.ProductSet)  * max(self.Instance.MaimumLeadTime, 1))),
                                     ub=[0.0] * ((len(self.Instance.ProductSet)  * max(self.Instance.MaimumLeadTime, 1))))

        # Define the variable name.
        # Usefull for debuging purpose. Otherwise, disable it, it is time consuming.
        if Constants.Debug:
            quantityvars = []
            consumptionvars = []
            inventoryvars = []
            productionvars = []
            backordervars = []
            svariablevar =[]
            qfixvar = []
            hasleftoverVar = []
            initialinventoryvar = []
            for p in self.Instance.ProductSet:
                for t in self.Instance.TimeBucketSet:
                    for w in self.ScenarioSet:
                        quantityvars.append(((int)(self.GetIndexQuantityVariable(p, t, w)), self.GetNameQuantityVariable(p, t, w)))

                        for c in self.Instance.ConsumptionSet:
                                consumptionvars.append(((int)(self.GetIndexConsumptionVariable(c[0], c[1], t, w)),
                                                              self.GetNameConsumptionVariable(c[0], c[1], t, w)))

                        if w == 0 or self.ExpendFirstNode:
                            productionvars.append(((int)(self.GetIndexProductionVariable(p, t, w)), self.GetNameProductionVariable(p, t, w)))
                        inventoryvars.append(((int)(self.GetIndexInventoryVariable(p, t, w)), self.GetNameInventoryVariable(p, t, w)))
                        if self.Instance.HasExternalDemand[p]:
                            backordervars.append(((int)(self.GetIndexBackorderVariable(p, t, w)), self.GetNameBackOrderQuantity(p, t, w)))

                for t in range(max(self.Instance.MaimumLeadTime, 1)):
                    if self.RollingHorizon:
                        initialinventoryvar.append(((int)(self.GetIndexInitialInventoryInRollingHorizon(p, t)), self.GetNameStartingInventory(p, t)))
            quantityvars = list(set(quantityvars))
            consumptionvars = list(set(consumptionvars))
            productionvars = list(set(productionvars))
            inventoryvars = list(set(inventoryvars))
            backordervars = list(set(backordervars))
            svariablevar = list(set(svariablevar))
            qfixvar = list(set(qfixvar))
            hasleftoverVar = list(set(hasleftoverVar))
            initialinventoryvar = list(set(initialinventoryvar))
            varnames = quantityvars + consumptionvars + inventoryvars + productionvars + backordervars + svariablevar + qfixvar+ hasleftoverVar+ initialinventoryvar
            self.Cplex.variables.set_names(varnames)



    # Print a constraint (usefull for debugging)
    def PrintConstraint( self, vars, coeff, righthandside):
        print("Add the following constraint:")
        print("----------------Var-----------------------------")
        print(vars)
        print("----------------Coeff-----------------------------")
        print(coeff)
        print("----------------Rhs-----------------------------")
        print(righthandside)

    # To evaluate the solution obtained with the expected demand, the solution quanitity are constraint to be equal to some values
    # This function creates the Capacity constraint
    def CreateCopyGivenQuantityConstraints(self):
        AlreadyAdded = [False for v in range(self.NrQuantityVariables)]
        self.QuantityConstraintNR = [[["" for t in self.Instance.TimeBucketSet] for p in self.Instance.ProductSet]
                                     for w in self.ScenarioSet]

        # Capacity constraint
        for p in self.Instance.ProductSet:
            for t in self.Instance.TimeBucketSet:
                for w in self.ScenarioSet:
                    indexvariable = self.GetIndexQuantityVariable(p, t, w)
                    if not AlreadyAdded[indexvariable] and (t <= self.FixSolutionUntil):

                        vars = [indexvariable]
                        AlreadyAdded[indexvariable] = True
                        coeff = [1.0]

                        righthandside = [float(self.GivenQuantity[t][p])]
                        #self.PrintConstraint(vars, coeff, righthandside)
                        self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                          senses=["E"],
                                                          rhs=righthandside,
                                                          names=["LQuantitya%da%da%d"%(p,t,w)])

                        self.QuantityConstraintNR[w][p][t] = "Quantitya%da%da%d"%(p,t,w)

        # To evaluate the solution obtained with the expected demand, the solution quanitity are constraint to be equal to some values
        # This function creates the Capacity constraint

    def CreateCopyGivenConumptionConstraints(self):
        AlreadyAdded = [False for v in range(self.NrConsumptionVariables)]
        self.ConsumptionConstraintNR = [[["" for t in self.Instance.TimeBucketSet]
                                         for c in self.Instance.ConsumptionSet]
                                        for w in self.ScenarioSet]

        # Capacity constraint
        for c in self.Instance.ConsumptionSet:
            idc = self.Instance.ConsumptionSet.index(c)
            for t in self.Instance.TimeBucketSet:
                for w in self.ScenarioSet:
                    indexvariable = int(self.GetIndexConsumptionVariable(c[0], c[1], t, w))
                    if not AlreadyAdded[indexvariable - self.StartConsumptionVariable] and (t <= self.FixSolutionUntil):
                        vars = [indexvariable]
                        AlreadyAdded[indexvariable - self.StartConsumptionVariable] = True
                        coeff = [1.0]

                        righthandside = [float(self.GivenConsumption[t][idc])]
                        # self.PrintConstraint(vars, coeff, righthandside)
                        self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                          senses=["E"],
                                                          rhs=righthandside,
                                                          names=["FixConsumptiona%da%da%da%d" % (c[0], c[1], t, w)])

                        self.ConsumptionConstraintNR[w][idc][t] = "FixConsumptiona%da%da%da%d" % (c[0], c[1], t, w)

    def CreateCopyGivenSetupConstraints(self):

         self.SetupConstraint = [[["" for t in self.Instance.TimeBucketSet] for p in self.Instance.ProductSet]
                                 for w in self.ScenarioSet]

         AlreadyAdded = [False for v in range(self.GetNrProductionVariable())]
         # Setup equal to the given ones
         for p in self.Instance.ProductSet:
             for t in self.Instance.TimeBucketSet:
                 for w in self.ScenarioSet:
                      indexvariable = self.GetIndexProductionVariable(p, t, w)
                      indexinarray = indexvariable - self.GetStartProductionVariable()

                      if not AlreadyAdded[indexinarray]:
                            vars = [indexvariable]
                            AlreadyAdded[indexinarray] = True
                            coeff = [1.0]
                            righthandside = [round(self.GivenSetup[t][p], 2)]
                            # PrintConstraint( vars, coeff, righthandside )
                            name = "Setup%da%da%d" % (p, t, w)
                            self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                              senses=["E"],
                                                              rhs=righthandside,
                                                              names=[name])
                            self.SetupConstraint[w][p][t] = name

    def WarmStartGivenSetupConstraints(self):
         AlreadyAdded = [False for v in range(self.GetNrProductionVariable())]
         vars=[]
         righthandside = []
         # Setup equal to the given ones
         for p in self.Instance.ProductSet:
              for t in self.Instance.TimeBucketSet:
                  for w in self.ScenarioSet:
                      indexvariable = self.GetIndexProductionVariable(p, t, w)
                      indexinarray = indexvariable - self.GetStartProductionVariable()

                      if not AlreadyAdded[indexinarray]:
                          vars = vars + [indexvariable]
                          AlreadyAdded[indexinarray] = True
                          righthandside = righthandside + [round(self.GivenSetup[t][p], 0)]
         self.Cplex.MIP_starts.add(cplex.SparsePair(vars, righthandside), self.Cplex.MIP_starts.effort_level.solve_fixed )



    # Demand and materials requirement: set the value of the invetory level and backorder quantity according to
    #  the quantities produced and the demand
    def CreateFlowConstraints(self):

        decentralized = DecentralizedMRP(self.Instance, self.UseSafetyStockGrave)
        if self.UseSafetyStock:
            safetystock = decentralized.ComputeSafetyStock()

        if self.UseSafetyStockGrave:
            safetystock = decentralized.ComputeSafetyStockGrave()


        #print "safet s %s"%safetystock
        self.FlowConstraintNR = [[["" for t in self.Instance.TimeBucketSet]
                                  for p in self.Instance.ProductSet]
                                 for w in self.ScenarioSet]
        AlreadyAdded = [False for w in range(self.GetNrInventoryVariable())]

        for p in self.Instance.ProductSet:
            for w in self.ScenarioSet:
                # To speed up the creation of the model, only the variable and coffectiant which were not in the previous constraints are added (See the model definition)
                righthandside = [-1 * self.Instance.StartingInventories[p]]
                quantityvar = []
                quantityvarceoff = []
                dependentdemandvar = []
                dependentdemandvarcoeff = []
                startinginventoryinrollinghorizon = []
                startinginventoryinrollinghorizoncoeff = []

                for t in self.Instance.TimeBucketSet:
                    indexinventoryvar = self.GetIndexInventoryVariable(p, t, w) - self.GetStartInventoryVariable()
                    backordervar = []

                    if t == self.DemandKnownUntil -1:
                            #reset right hand side because the demand afterward is saved in a variable to accelerate the update of the MIP
                            righthandside = [-1 * self.Instance.StartingInventories[p]]

                    else:
                            righthandside[0] = righthandside[0] + self.Scenarios[w].Demands[t][p]


                    if self.UseSafetyStock and t >= self.DemandKnownUntil:
                            righthandside[0] = righthandside[0] + safetystock[t][p]


                    if self.Instance.HasExternalDemand[p] :
                            backordervar = [self.GetIndexBackorderVariable(p, t, w)]

                    if t - self.Instance.LeadTimes[p] >= 0:
                            quantityvar = quantityvar + [self.GetIndexQuantityVariable(p, t - self.Instance.LeadTimes[p], w)]
                            quantityvarceoff = quantityvarceoff + [1.0]

                    dependentdemandvar = dependentdemandvar + [int(self.GetIndexConsumptionVariable(p,c[1],t,w))
                                                               for c in self.Instance.ConsumptionSet
                                                               if c[0] == p
                                                                ]

                    dependentdemandvarcoeff = dependentdemandvarcoeff + [-1.0  for co in self.Instance.ConsumptionSet if co[0] == p  ]




                    inventoryvar = [self.GetIndexInventoryVariable(p, t, w)]

                    knondemand = []
                    knondemandcoeff = []
                    if self.DemandKnownUntil>=0 and t >= (self.DemandKnownUntil-1) and self.Instance.HasExternalDemand[p]:
                            knondemand = [self.GetIndexKnownDemand(p)]
                            knondemandcoeff = [-1.0]

                    if self.RollingHorizon and t < self.Instance.MaimumLeadTime:
                        startinginventoryinrollinghorizon = startinginventoryinrollinghorizon + [self.GetIndexInitialInventoryInRollingHorizon(p, t)]
                        startinginventoryinrollinghorizoncoeff = startinginventoryinrollinghorizoncoeff + [1.0]

                    vars = inventoryvar + backordervar + quantityvar + dependentdemandvar + knondemand \
                            + startinginventoryinrollinghorizon

                    coeff = [-1.0] * len(inventoryvar) \
                                + [1.0] * len(backordervar) \
                                + quantityvarceoff \
                                + dependentdemandvarcoeff \
                                + knondemandcoeff \
                                + startinginventoryinrollinghorizoncoeff

                    if len(vars) > 0:
                            if not AlreadyAdded[indexinventoryvar]:
                                AlreadyAdded[indexinventoryvar] = True
                                #self.PrintConstraint(vars, coeff, righthandside)
                                self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                                  senses=["E"],
                                                                  rhs=righthandside,
                                                                  names=["Flowa%da%da%d"%(p,t,w)])
                    self.FlowConstraintNR[w][p][t] = "Flowa%da%da%d"%(p,t,w)

    # This function creates the  indicator constraint to se the production variable to 1 when a positive quantity is produce
    def CreateLSInequalities(self):
        for p in self.Instance.ProductWithExternalDemand:
            for w in self.ScenarioSet:
                for l in range(self.Instance.Leadtimes[p], self.Instance.NrTimeBucket):
                    for r in range(l+1):
                            S = range(r, l+1)
                            vars = [self.GetIndexQuantityVariable(p, t - self.Instance.Leadtimes[p], w) for t in S] \
                                    + [self.GetIndexProductionVariable(p, t - self.Instance.Leadtimes[p], w) for t in S] \
                                    + [self.GetIndexInventoryVariable(p, l, w)]
                            coeff = [1 for t in S] \
                                    + [-sum(self.Scenarios[w].Demands[tau][p] for tau in range( t,l +1)) for t in S] \
                                    + [-1]

                            self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                              senses=["L"],
                                                              rhs=[0])

    def CreateQuantityAlternateConstraints(self):
        n = self.NrQuantityVariables

        for t in self.Instance.TimeBucketSet:

                for k in self.Instance.ProductSet:
                    if self.Instance.IsMaterProduct(k):
                        for w in self.ScenarioSet:
                            #if self.Instance.Requirements[p][k] > 0.0 :
                                vars = [self.GetIndexQuantityVariable(p,t,w)  for p in self.Instance.ProductSet]
                                coeff = [-1.0*self.Instance.Requirements[p][k]  for p in self.Instance.ProductSet]
                                for q in self.Instance.ProductSet:
                                    if self.Instance.Alternates[q][k] :
                                        vars = vars + [ int(self.GetIndexConsumptionVariable(q, k, t, w))]
                                        coeff = coeff + [1.0]
                                        righthandside = [0.0]
                                        #self.PrintConstraint(vars, coeff, righthandside)
                                        self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                                          senses=["E"],
                                                                          rhs=righthandside,
                                                                          names=["quantityConsumption%da%da%da%d" % (q, k, t, w)])#



    # This function creates the  indicator constraint to se the production variable to 1 when a positive quantity is produce
    def CreateProductionConstraints(self):
        n = self.NrQuantityVariables
        AlreadyAdded = [[False] * n for w in range(self.GetNrProductionVariable())]
        self.BigMConstraintNR = [[["" for t in self.Instance.TimeBucketSet] for p in self.Instance.ProductSet] for w in  self.ScenarioSet]

        BigM = [MIPSolver.GetBigMValue(self.Instance, self.Scenarios, p, ssgrave=self.GivenSSGrave) for p in self.Instance.ProductSet ]

        for t in self.Instance.TimeBucketSet:
            if t > self.FixSolutionUntil or not  self.EvaluateSolution:
                for p in self.Instance.ProductSet:
                    for w in self.ScenarioSet:
                        indexQ = self.GetIndexQuantityVariable(p, t, w)
                        indexP = self.GetIndexProductionVariable(p, t, w) - self.GetStartProductionVariable()
                        if not AlreadyAdded[indexP][indexQ]:

                            vars = [indexQ, self.GetIndexProductionVariable(p, t, w)]
                            AlreadyAdded[indexP][indexQ] = True
                            coeff = [-1.0, BigM[p]]
                            righthandside = [0.0]

                            #self.PrintConstraint(vars, coeff, righthandside)
                            self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                              senses=["G"],
                                                              rhs=righthandside,
                                                              names=["BigM%da%da%d" % (p, t, w)])#


                        self.BigMConstraintNR[w][p][t] = "BigM%da%da%d" % (p, t, w)

    # This function add the objective function as a variable
    def CreateTotalCostConstraint(self):

        nextvar= 0
        for productset in [ self.Instance.ProductWithExternalDemand, self.Instance.ProductWithoutExternalDemand ]:
            vars = [self.GetIndexTotalCost() + nextvar]
            nextvar = nextvar +1
            coeff = [1]

            for p in productset:
                for t in self.Instance.TimeBucketSet:
                    vars = vars + [self.GetIndexProductionVariable(p, t, 0)]
                    coeff = coeff + [-1 *np.power(self.Instance.Gamma, t) * self.Instance.SetupCosts[p] ]

            indice = len(coeff)

            nrinventory =  len( productset ) * (self.DemandScenarioTree.NrNode - 2)
            nribackorder = self.NrBackorderVariableWithoutNonAnticipativity
            if nextvar == 2: #(components)
                nribackorder = 0
            indicecoeffiunventory = [-1 for w in range(self.NrInventoryVariableWithoutNonAnticipativity)]

            indicecoeffbackorders = [-1 for w in range(self.NrBackorderVariableWithoutNonAnticipativity)]

            coeff = coeff + [ 0 for i in range(nrinventory + nribackorder)  ]
            for p in productset:
                for t in self.Instance.TimeBucketSet:
                    for w in self.ScenarioSet:
                         multiplier = -1 * self.Scenarios[w].Probability * np.power(self.Instance.Gamma, t)

                         indexI =  self.GetIndexInventoryVariable(p, t, w) - self.StartInventoryVariableWithoutNonAnticipativity
                         if indicecoeffiunventory[indexI]  == -1:
                            vars = vars + [ self.GetIndexInventoryVariable(p, t, w)]
                            indicecoeffiunventory[ indexI ] = indice
                            indice = indice + 1
                         if self.Instance.HasExternalDemand[p]:
                             indexB =  self.GetIndexBackorderVariable(p, t, w) - self.StartBackorderVariableWithoutNonAnticipativity
                             if indicecoeffbackorders[indexB] == -1:
                                 vars = vars + [self.GetIndexBackorderVariable(p, t, w)]
                                 indicecoeffbackorders[indexB] = indice
                                 indice = indice + 1
                             if t == self.Instance.NrTimeBucket -1:
                                 coeff[indicecoeffbackorders[indexB]] = coeff[indicecoeffbackorders[indexB]] + multiplier * \
                                                                                                               self.Instance.LostSaleCost[
                                                                                                                   p]
                             else:
                                coeff[indicecoeffbackorders[indexB]] = coeff[indicecoeffbackorders[indexB]] + multiplier * \
                                                                                                       self.Instance.BackorderCosts[
                                                                                                           p]

                         coeff[indicecoeffiunventory[indexI]] = coeff[indicecoeffiunventory[indexI]] + multiplier * self.Instance.InventoryCosts[p]


            righthandside = [0]
            self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                           senses=["E"],
                                                           rhs=righthandside)

        vars = [self.GetIndexTotalCost()]
        coeff = [1]
        righthandside = [0]
        for p in self.Instance.ProductWithExternalDemand:
             for t in self.Instance.TimeBucketSet:
                    if t + self.Instance.Leadtimes[p] < self.Instance.NrTimeBucket:
                        demand = np.power(self.Instance.Gamma, t + self.Instance.Leadtimes[p] -1)  \
                                * self.Instance.InventoryCosts[p] \
                                * sum(self.Scenarios[w].Demands[t + self.Instance.Leadtimes[p]][p] * self.Scenarios[w].Probability
                                      for w in self.ScenarioSet)
                    else: demand=0
                    vars = vars + [self.GetIndexProductionVariable(p, t , 0)]
                    coeficient = - np.power(self.Instance.Gamma, t) * self.Instance.SetupCosts[p]
                    for w in self.ScenarioSet:
                        if t + self.Instance.Leadtimes[p] < self.Instance.NrTimeBucket:
                            coeficient = coeficient + demand
                    coeff = coeff + [(coeficient)]
                    righthandside[0] = righthandside[0] + demand

        self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                           senses=["G"],
                                           rhs=righthandside)



    # This function creates the Capacity constraint
    def CreateCapacityConstraints(self):

        secenarioset = [0]
        # < or >
        if self.Model < Constants.ModelYQFix:
            secenarioset = self.ScenarioSet
        # Capacity constraint
        if self.Instance.NrResource > 0:
            for k in range(self.Instance.NrResource):
                AlreadyAdded = [False for v in range(self.NrQuantityVariables)]

                for t in self.Instance.TimeBucketSet:
                    for w in secenarioset:
                        indexQ = self.GetIndexQuantityVariable(0, t, w)
                        if not AlreadyAdded[indexQ]:
                            AlreadyAdded[indexQ] = True
                            vars = [self.GetIndexQuantityVariable(p, t, w) for p in self.Instance.ProductSet]
                            coeff = [float(self.Instance.ProcessingTime[p][k]) for p in self.Instance.ProductSet]
                            righthandside = [float(self.Instance.Capacity[k])]
                            #self.PrintConstraint(vars, coeff, righthandside)
                            self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                              senses=["L"],
                                                              rhs=righthandside)



#                        self.CreateSafetyStockConstraints()
                        # This function creates the Capacity constraint

    # def CreateSafetyStockConstraints(self):
    #      AlreadyAdded = [False for v in range(self.GetNrQuantityVariable())]
    #      for p in self.Instance.ProductWithExternalDemand:
    #         for t in self.Instance.TimeBucketSet:
    #             for w in self.ScenarioSet:
    #                 indexI = self.GetIndexInventoryVariable(p, t, w)
    #                 #if not AlreadyAdded[indexI]:
    #                    # AlreadyAdded[indexI] = True
    #                 vars = [indexI ]
    #                 coeff = [ 1.0 ]
    #                 righthandside = [ ScenarioTreeNode.TransformInverse([[0.99]],
    #                                                                    1,
    #                                                                    1,
    #                                                                    self.Instance.Distribution,
    #                                                                    [self.Instance.ForecastedAverageDemand[t][p]],
    #                                                                    [self.Instance.ForcastedStandardDeviation[t][p]] )[0][0] ]
    #                 self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff) ],
    #                                                                           senses=["G"],
    #                                                                           rhs=righthandside)

    # This function creates the non anticipitativity constraint
    def CreateNonanticipativityConstraints(self):
        AlreadyAdded = [[False for v in range(self.NrQuantityVariables)] for w in range(self.NrQuantityVariables)]
        considertimebucket = self.Instance.TimeBucketSet;
         # Non anticipitativity only for period 1 for now
        for w1 in self.ScenarioSet:
            for w2 in range(w1 + 1, self.NrScenario):
                for p in self.Instance.ProductSet:
                    for t in considertimebucket:
                        IndexQuantity1 = self.GetIndexQuantityVariable(p, t, w1)
                        IndexQuantity2 = self.GetIndexQuantityVariable(p, t, w2)
                        if self.Scenarios[w1].QuanitityVariable[t][p] == self.Scenarios[w2].QuanitityVariable[t][p] \
                                and not AlreadyAdded[IndexQuantity1][IndexQuantity2]:
                            AlreadyAdded[IndexQuantity1][IndexQuantity2] = True
                            AlreadyAdded[IndexQuantity2][IndexQuantity1] = True
                            if not ( self.Model == Constants.ModelYQFix ):
                                vars = [ self.GetIndexQuantityVariable(p, t, w1), self.GetIndexQuantityVariable(p, t, w2) ]
                                coeff = [1.0, -1.0]
                                righthandside = [0.0]

                                # PrintConstraint( vars, coeff, righthandside )
                                self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                         senses=["E"],
                                                         rhs=righthandside)

                            if not ( self.Model == Constants.ModelYQFix or self.Model == Constants.ModelYFix ):
                                vars = [ self.GetIndexProductionVariable(p, t, w1), self.GetIndexProductionVariable(p, t, w2) ]
                                coeff = [1.0, -1.0]
                                righthandside = [0.0]

                                # PrintConstraint( vars, coeff, righthandside )
                                self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                                  senses=["E"],
                                                                  rhs=righthandside)


     # This function creates the non anticipitativity constraint
    #For debug purpose, transfor the multi stage in two stage by adding the required constraints

    def GetEchelonRequirement(self):
        extendedrequirement = [[1 if p == q else self.Instance.Requirements[q][p] for p in self.Instance.ProductSet] for
                               q in self.Instance.ProductSet]
        levelset = sorted(set(self.Instance.Level), reverse=False)

        for l in levelset:
            if l > 2:
                prodinlevel = [p for p in self.Instance.ProductSet if self.Instance.Level[p] == l]
                prodinnextlevel = [p for p in self.Instance.ProductSet if self.Instance.Level[p] == l - 1]
                for p in prodinlevel:
                    for q in self.Instance.ProductSet:
                        extendedrequirement[q][p] = sum(
                            self.Instance.Requirements[q][j] * extendedrequirement[j][p] for j in prodinnextlevel) \
                                                    + extendedrequirement[q][p]

        return extendedrequirement

    def AddLinkingConstraintsYSQ(self):
        AlreadyAdded = [False for w in range(self.NrQuantityVariables)]

        BigM2 = [MIPSolver.GetBigMDemValue(self.Instance, self.Scenarios, p) for p in self.Instance.ProductSet]

        extendedrequirement = self.GetEchelonRequirement()

        for w in self.ScenarioSet:
            for p in self.Instance.ProductSet:
                for t in self.Instance.TimeBucketSet:
                    IndexQuantity = self.GetIndexQuantityVariable(p, t, w)
                    if not AlreadyAdded[IndexQuantity]:
                        AlreadyAdded[IndexQuantity]= True
                        varsecheloninv = []
                        coeffecheloninv = []
                        if t > 0:
                            for q in self.Instance.ProductSet:
                                varsecheloninv.append(self.GetIndexInventoryVariable(q, t - 1, w))
                                coeffecheloninv.append(1.0 * extendedrequirement[q][p])
                                for tau in range(t - self.Instance.Leadtimes[q], t):
                                    varsecheloninv.append(self.GetIndexQuantityVariable(q, tau, w))
                                    coeffecheloninv.append(1.0 * extendedrequirement[q][p])

                                if self.Instance.HasExternalDemand[q]:
                                    varsecheloninv.append(self.GetIndexBackorderVariable(q, t - 1, w))
                                    coeffecheloninv.append(-1.0 * extendedrequirement[q][p])

                        M = BigM2[p]

                        coeff = coeffecheloninv + [1.0, -1.0]
                        vars = varsecheloninv + \
                               [self.GetIndexQuantityVariable(p, t, w),
                                self.GetIndexSVariable(p, t)]
                        righthandside = [0.0]
                        #
                        # # PrintConstraint( vars, coeff, righthandside )
                        self.Cplex.linear_constraints.add(
                            lin_expr=[cplex.SparsePair(vars, coeff)],
                            senses=["L"],
                            rhs=righthandside)

                        #####################################################################################
                        coeff = coeffecheloninv + [1.0, -1.0, -1.0 * M]
                        vars = varsecheloninv + \
                               [self.GetIndexQuantityVariable(p, t, w),
                                self.GetIndexSVariable(p, t),
                                self.GetIndexHasLeftover(p, t,w)]

                        righthandside = [-1.0 * M]

                        self.Cplex.linear_constraints.add(
                            lin_expr=[cplex.SparsePair(vars, coeff)],
                            senses=["G"],
                            rhs=righthandside)

    def AddConstraintsComputeQuantityBasedOnFix(self):
        AlreadyAdded = [False for w in range(self.NrQuantityVariables)]

        BigM2 = [MIPSolver.GetBigMDemValue(self.Instance, self.Scenarios, p) for p in self.Instance.ProductSet]
        for w in self.ScenarioSet:
            for p in self.Instance.ProductSet:
                for t in self.Instance.TimeBucketSet:
                    IndexQuantity = self.GetIndexQuantityVariable(p, t, w)
                    if not AlreadyAdded[IndexQuantity]:
                        AlreadyAdded[IndexQuantity] = True
                        coeff = [-1.0, 1.0]
                        vars = [self.GetIndexQuantityVariable(p, t, w),
                                self.GetIndexFixedQuantity(p, t)]

                        righthandside = [0.0]

                        self.Cplex.linear_constraints.add(
                            lin_expr=[cplex.SparsePair(vars, coeff)],
                            senses=["G"],
                            rhs=righthandside)

                        M = BigM2[p]

                        coeff = [-1.0, 1.0, -1.0*M]
                        vars = [self.GetIndexQuantityVariable(p, t, w),
                                self.GetIndexFixedQuantity(p, t),
                                self.GetIndexHasLeftover(p, t, w)]
                        righthandside = [0.0]
                        #
                        # # PrintConstraint( vars, coeff, righthandside )
                        self.Cplex.linear_constraints.add(
                            lin_expr=[cplex.SparsePair(vars, coeff)],
                            senses=["L"],
                            rhs=righthandside)

    def AddConstraintsComputeLeftOver(self):

        BigM2 = [MIPSolver.GetBigMDemValue(self.Instance, self.Scenarios, p) for p in self.Instance.ProductSet]

        extendedrequirement = self.GetEchelonRequirement()

        for w in self.ScenarioSet:
            for p in self.Instance.ProductSet:
                for t in self.Instance.TimeBucketSet:

                    varsecheloninv = []
                    coeffecheloninv = []
                    if t > 0:
                        for q in self.Instance.ProductSet:
                            varsecheloninv.append(self.GetIndexInventoryVariable(q, t - 1, w))
                            coeffecheloninv.append(1.0 * extendedrequirement[q][p])
                            for tau in range(t - self.Instance.Leadtimes[q], t):
                                varsecheloninv.append(self.GetIndexQuantityVariable(q, tau, w))
                                coeffecheloninv.append(1.0 * extendedrequirement[q][p])

                            if self.Instance.HasExternalDemand[q]:
                                varsecheloninv.append(self.GetIndexBackorderVariable(q, t - 1, w))
                                coeffecheloninv.append(-1.0 * extendedrequirement[q][p])


                    M = BigM2[p]

                    coeff = coeffecheloninv + [1.0, -1.0, -1.0 * M]
                    vars = varsecheloninv + \
                           [self.GetIndexFixedQuantity(p, t),
                            self.GetIndexSVariable(p,t),
                            self.GetIndexHasLeftover(p, t, w)]
                    righthandside = [0.0]
                    #
                    # # PrintConstraint( vars, coeff, righthandside )
                    self.Cplex.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(vars, coeff)],
                        senses=["L"],
                        rhs=righthandside)

                    varsecheloninv = []
                    coeffecheloninv = []
                    if t > 0:
                        for q in self.Instance.ProductSet:
                            varsecheloninv.append(self.GetIndexInventoryVariable(q, t - 1, w))
                            coeffecheloninv.append(-1.0 * extendedrequirement[q][p])
                            for tau in range(t - self.Instance.Leadtimes[q], t):
                                 varsecheloninv.append(self.GetIndexQuantityVariable(q, tau, w))
                                 coeffecheloninv.append(-1.0 * extendedrequirement[q][p])

                                 if self.Instance.HasExternalDemand[q]:
                                     varsecheloninv.append(self.GetIndexBackorderVariable(q, t - 1, w))
                                     coeffecheloninv.append( 1.0 * extendedrequirement[q][p])

                    coeff = coeffecheloninv + [-1.0, +1.0, 1.0*M ]
                    vars = varsecheloninv + \
                           [self.GetIndexFixedQuantity(p, t),
                            self.GetIndexSVariable(p, t),
                            self.GetIndexHasLeftover(p, t, w)]
                    righthandside = [M]
                    #
                    # # PrintConstraint( vars, coeff, righthandside )
                    self.Cplex.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(vars, coeff)],
                        senses=["L"],
                        rhs=righthandside)



    def AddLinkingConstraintsSQ(self):

        BigM = [MIPSolver.GetBigMValue(self.Instance, self.Scenarios, p) for p in self.Instance.ProductSet]
        BigM2 = [MIPSolver.GetBigMDemValue(self.Instance, self.Scenarios, p) for p in self.Instance.ProductSet]
        M = sum(BigM2[p] for p in self.Instance.ProductSet)
        extendedrequirement = self.GetEchelonRequirement()

        for w in self.ScenarioSet:
              for p in self.Instance.ProductSet:
                    for t in self.Instance.TimeBucketSet:

                           varsecheloninv =[]
                           coeffecheloninv = []
                           if t>0:
                               for q in self.Instance.ProductSet:
                                   varsecheloninv.append(self.GetIndexInventoryVariable(q,t-1,w))
                                   coeffecheloninv.append( 1.0 * extendedrequirement[q][p] )
                                   for tau in range( t - self.Instance.Leadtimes[q], t):
                                       varsecheloninv.append(self.GetIndexQuantityVariable(q, tau, w))
                                       coeffecheloninv.append(1.0 * extendedrequirement[q][p])


                                   if self.Instance.HasExternalDemand[q]:
                                       varsecheloninv.append(self.GetIndexBackorderVariable(q, t - 1, w))
                                       coeffecheloninv.append(-1.0 * extendedrequirement[q][p])



                           #M = BigM2[p]#sum( BigM[q] * extendedrequirement[q][p] for q in self.Instance.ProductWithExternalDemand  )
                           #req = [extendedrequirement[q][p] for q in self.Instance.ProductSet]
                           #print " %s : %s"%(p, req)
                           #print "%s vs %s vs %s"%( M, BigM[p], BigM2[p] )

                           coeff = coeffecheloninv + [1.0,  -1.0, M]
                           vars = varsecheloninv +\
                                   [self.GetIndexQuantityVariable(p, t, w),
                                       self.GetIndexSVariable(p, t),
                                       self.GetIndexProductionVariable(p, t, w)]
                           righthandside = [M]
                           #
                           # # PrintConstraint( vars, coeff, righthandside )
                           self.Cplex.linear_constraints.add(
                                                    lin_expr=[cplex.SparsePair(vars, coeff)],
                                                    senses=["L"],
                                                    rhs=righthandside)

                           coeff = coeffecheloninv + [1.0,  -1.0, -1.0 * M]
                           righthandside = [ -1.0 * M ]

                           self.Cplex.linear_constraints.add(
                                lin_expr=[cplex.SparsePair(vars, coeff)],
                                senses=["G"],
                                rhs=righthandside)

        for p in self.Instance.ProductSet:
               for t in self.Instance.TimeBucketSet:

                      coeff =   [1.0, -1.0* M]
                      vars =   [ self.GetIndexSVariable(p, t),
                                 self.GetIndexProductionVariable(p, t, 0)]
                      righthandside = [0.0]
        #
                      #self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                      #                                  senses=["L"],
                      #                                  rhs=righthandside)

    # For debug purpose, transfor the multi stage in two stage by adding the required constraints

    def CreateTwostageFromMultistageConstraints(self):
        AlreadyAdded = [[False for v in range(self.NrQuantityVariables)] for w in range(self.NrQuantityVariables)]
        for w1 in self.ScenarioSet:
            for w2 in self.ScenarioSet:
                    for p in self.Instance.ProductSet:
                          for t in self.Instance.TimeBucketSet:
                               IndexQuantity1 = self.GetIndexQuantityVariable(p, t, w1)
                               IndexQuantity2 = self.GetIndexQuantityVariable(p, t, w2)
                               
                               # < or >
                               if not AlreadyAdded[IndexQuantity1][ IndexQuantity2] and IndexQuantity1 < IndexQuantity2:
                                   AlreadyAdded[IndexQuantity1][IndexQuantity2] = True
                                   AlreadyAdded[IndexQuantity2][IndexQuantity1] = True
                                   vars = [IndexQuantity1, IndexQuantity2]
                                   coeff = [1.0, -1.0]
                                   righthandside = [0.0]

                                   # PrintConstraint( vars, coeff, righthandside )
                                   self.Cplex.linear_constraints.add( lin_expr=[cplex.SparsePair(vars, coeff)],
                                                                      senses=["E"],
                                                                      rhs=righthandside )

    def AddConstraintSafetyStock( self ):

        timetoenditem = self.Instance.GetTimeToEnd()
        #print "timetoenditem %s"%timetoenditem
        decentralized = DecentralizedMRP(self.Instance, self.UseSafetyStockGrave)


        if len(self.GivenSSGrave) > 0 :
            safetystock = self.GivenSSGrave#decentralized.ComputeSafetyStockGraveGivenSSI(self.GivenS, self.GivenSI)
        else:
            safetystock = decentralized.ComputeSafetyStockGrave()

       # print "safetystock %s"%safetystock
        AlreadyAdded = [False for v in range(self.GetNrInventoryVariable())]
        for w in self.ScenarioSet:
            for p in self.Instance.ProductSet:
                 for t in self.Instance.TimeBucketSet:
                     IndexInventory1 = self.GetIndexInventoryVariable(p, t, w)
                     positionvar = self.GetStartInventoryVariable() - IndexInventory1
                     if (not AlreadyAdded[positionvar]) \
                             and self.Instance.MaximumQuanityatT[t][p] > safetystock[t][p] \
                             and (self.Instance.NrTimeBucket - t > timetoenditem[p] or not self.Instance.ActualEndOfHorizon) :

                              AlreadyAdded[positionvar] = True
                              vars = [IndexInventory1, self.GetIndexSafetystockPenalty(p, t)]
                              coeff = [1.0,1.0]

                              self.Cplex.linear_constraints.add(lin_expr=[cplex.SparsePair(vars, coeff)],
                                                                 senses=["G"],
                                                                 rhs=[safetystock[t][p]])


    # Define the constraint of the model
    def CreateConstraints( self ):
        if Constants.Debug:
            print("Creat flow constraints ...")
        self.CreateFlowConstraints()
        self.CreateQuantityAlternateConstraints()
        #if len(self.GivenQuantity) == 0:
        if Constants.Debug:
            print("Creat production constraints ...")
        if not (self.EvaluateSolution or self.YFixHeuristic):
            self.CreateProductionConstraints()
        if Constants.Debug:
            print("Creat capacity constraints ...")
        self.CreateCapacityConstraints()
        if not self.UseImplicitNonAnticipativity and not self.EVPI:
            if Constants.Debug:
                print("Creat non anticipativity  constraints ...")
            self.CreateNonanticipativityConstraints( )
        if self.EvaluateSolution or self.YFixHeuristic:
            if Constants.Debug:
                print("Creat given setup and given setup...")
            self.CreateCopyGivenSetupConstraints()

        if self.WamStart:
            self.WarmStartGivenSetupConstraints()

        if self.UseSafetyStockGrave:
            self.AddConstraintSafetyStock()

        if self.EvaluateSolution:
            if self.Model == Constants.ModelYQFix or self.Model == Constants.ModelYFix:
                if Constants.Debug:
                    print("Creat given setup and given quantity...")
                self.CreateCopyGivenQuantityConstraints()
                self.CreateCopyGivenConumptionConstraints()


    #This function build the CPLEX model
    def BuildModel( self ):
        #Create the variabbles and constraints
        if Constants.Debug:
            print("start to creat variables ...")
        self.CreateVariable()
        if Constants.Debug:
            print("start to creat constraints ...")
        self.CreateConstraints()



    def TuneCplexParamter(self):
       # self.Cplex.parameters.mip.strategy.probe.set(3)
        if self.MipSetting == "Probing00":
            self.Cplex.parameters.mip.strategy.probe.set(-1)
        elif self.MipSetting == "Probing0":
            self.Cplex.parameters.mip.strategy.probe.set(0)
        elif self.MipSetting == "Probing1":
            self.Cplex.parameters.mip.strategy.probe.set(1)
        elif self.MipSetting == "Probing2":
            self.Cplex.parameters.mip.strategy.probe.set(2)
        elif self.MipSetting == "Probing3":
            self.Cplex.parameters.mip.strategy.probe.set(3)
        elif self.MipSetting == "CutFactor10":
            self.Cplex.parameters.mip.limits.cutsfactor.set(10)
        elif self.MipSetting == "emphasis0":
            self.Cplex.parameters.emphasis.mip.set(0)
        elif self.MipSetting == "emphasis1":
            self.Cplex.parameters.emphasis.mip.set(1)
        elif self.MipSetting == "emphasis2":
            self.Cplex.parameters.emphasis.mip.set(2)
        elif self.MipSetting == "emphasis3":
            self.Cplex.parameters.emphasis.mip.set(3)
        elif self.MipSetting == "emphasis4":
            self.Cplex.parameters.emphasis.mip.set(4)
        elif self.MipSetting == "localbranching":
            self.Cplex.parameters.mip.strategy.lbheur.set(1)
        elif self.MipSetting == "heuristicfreq10":
            self.Cplex.parameters.mip.strategy.heuristicfreq.set(10)
        elif self.MipSetting == "feasibilitypomp0":
            self.Cplex.parameters.mip.strategy.fpheur.set(0)
        elif self.MipSetting == "feasibilitypomp1":
            self.Cplex.parameters.mip.strategy.fpheur.set(1)
        elif self.MipSetting == "feasibilitypomp2":
            self.Cplex.parameters.mip.strategy.fpheur.set(2)
        elif self.MipSetting == "BB":
            self.Cplex.parameters.mip.strategy.search.set(1)
        elif self.MipSetting == "flowcovers1":
            self.Cplex.parameters.mip.cuts.flowcovers.set(1)
        elif self.MipSetting == "flowcovers2":
            self.Cplex.parameters.mip.cuts.flowcovers.set(2)
        elif self.MipSetting == "pathcut1":
            self.Cplex.parameters.mip.cuts.pathcut.set(1)
        elif self.MipSetting == "pathcut2":
            self.Cplex.parameters.mip.cuts.pathcut.set(2)
        elif self.MipSetting == "gomory1":
            self.Cplex.parameters.mip.cuts.gomory.set(1)
        elif self.MipSetting == "gomor2":
            self.Cplex.parameters.mip.cuts.gomory.set(2)
        elif self.MipSetting == "zerohalfcut1":
            self.Cplex.parameters.mip.cuts.zerohalfcut.set(1)
        elif self.MipSetting == "zerohalfcut2":
            self.Cplex.parameters.mip.cuts.zerohalfcut.set(2)
        elif self.MipSetting == "mircut1":
            self.Cplex.parameters.mip.cuts.mircut.set(1)
        elif self.MipSetting == "mircut2":
            self.Cplex.parameters.mip.cuts.mircut.set(2)
        elif self.MipSetting == "implied1":
            self.Cplex.parameters.mip.cuts.implied.set(1)
        elif self.MipSetting == "implied2":
            self.Cplex.parameters.mip.cuts.implied.set(2)
        elif self.MipSetting == "gubcovers1":
            self.Cplex.parameters.mip.cuts.gubcovers.set(1)
        elif self.MipSetting == "gubcovers2":
            self.Cplex.parameters.mip.cuts.gubcovers.set(2)
        elif self.MipSetting == "disjunctive1":
            self.Cplex.parameters.mip.cuts.disjunctive.set(1)
        elif self.MipSetting == "disjunctive2":
            self.Cplex.parameters.mip.cuts.disjunctive.set(2)
        elif self.MipSetting == "disjunctive3":
            self.Cplex.parameters.mip.cuts.disjunctive.set(3)
        elif self.MipSetting == "covers1":
            self.Cplex.parameters.mip.cuts.covers.set(1)
        elif self.MipSetting == "covers2":
            self.Cplex.parameters.mip.cuts.covers.set(2)
        elif self.MipSetting == "covers3":
            self.Cplex.parameters.mip.cuts.covers.set(3)
        elif self.MipSetting == "cliques1":
            self.Cplex.parameters.mip.cuts.cliques.set(1)
        elif self.MipSetting == "cliques2":
            self.Cplex.parameters.mip.cuts.cliques.set(2)
        elif self.MipSetting == "cliques3":
            self.Cplex.parameters.mip.cuts.cliques.set(3)
        elif self.MipSetting == "allcutmax":
            self.Cplex.parameters.mip.cuts.cliques.set(3)
            self.Cplex.parameters.mip.cuts.covers.set(3)
            self.Cplex.parameters.mip.cuts.disjunctive.set(3)
            self.Cplex.parameters.mip.cuts.gubcovers.set(2)
            self.Cplex.parameters.mip.cuts.implied.set(2)
            self.Cplex.parameters.mip.cuts.mircut.set(2)
            self.Cplex.parameters.mip.cuts.zerohalfcut.set(2)
            self.Cplex.parameters.mip.cuts.gomory.set(2)
            self.Cplex.parameters.mip.cuts.pathcut.set(2)
            self.Cplex.parameters.mip.cuts.flowcovers.set(2)
        elif self.MipSetting == "variableselect00":
            self.Cplex.parameters.mip.strategy.variableselect.set(-1)
        elif self.MipSetting == "variableselect1":
            self.Cplex.parameters.mip.strategy.variableselect.set(1)
        elif self.MipSetting == "variableselect2":
            self.Cplex.parameters.mip.strategy.variableselect.set(2)
        elif self.MipSetting == "variableselect3":
            self.Cplex.parameters.mip.strategy.variableselect.set(3)
        elif self.MipSetting == "variableselect4":
            self.Cplex.parameters.mip.strategy.variableselect.set(4)
        elif self.MipSetting == "BranchUp":
            self.Cplex.parameters.mip.strategy.branch.set(-1)
        elif self.MipSetting == "BranchDefault":
            self.Cplex.parameters.mip.strategy.branch.set(0)
        elif self.MipSetting == "BranchDown":
            self.Cplex.parameters.mip.strategy.branch.set(1)
        elif self.MipSetting == "NoOtherCuts":
            self.Cplex.parameters.mip.cuts.cliques.set(-1)
            self.Cplex.parameters.mip.cuts.covers.set(-1)
            self.Cplex.parameters.mip.cuts.disjunctive.set(-1)
            self.Cplex.parameters.mip.cuts.gubcovers.set(-1)
            self.Cplex.parameters.mip.cuts.implied.set(-1)
            self.Cplex.parameters.mip.cuts.zerohalfcut.set(-1)
            self.Cplex.parameters.mip.cuts.flowcovers.set(-1)
        elif self.MipSetting == "cutmax":
             self.Cplex.parameters.mip.cuts.gomory.set(2)
             self.Cplex.parameters.mip.cuts.pathcut.set(2)
             self.Cplex.parameters.mip.cuts.mircut.set(2)
             self.Cplex.parameters.mip.cuts.cliques.set(-1)
             self.Cplex.parameters.mip.cuts.covers.set(-1)
             self.Cplex.parameters.mip.cuts.disjunctive.set(-1)
             self.Cplex.parameters.mip.cuts.gubcovers.set(-1)
             self.Cplex.parameters.mip.cuts.implied.set(-1)
             self.Cplex.parameters.mip.cuts.zerohalfcut.set(-1)
             self.Cplex.parameters.mip.cuts.flowcovers.set(-1)


    def ReadNrVariableConstraint(self, logfilename):

        nrvariable= 0
        nrconstraints = 0

        with open(logfilename, 'r') as searchfile:
            for line in searchfile:
                if 'Reduced LP has' in line or ('Reduced MIP has' in line and not "binaries" in line):
                    line = line.split()
                    nrvariable = int(line[5])
                    nrconstraints = int(line[3])
                    if Constants.Debug:
                        print("there are %r variables and %r constraints"%(nrvariable, nrconstraints))

        return nrvariable, nrconstraints

    #This function set the parameter of CPLEX, run Cplex, and return a solution
    def Solve( self, createsolution = True ):
        start_time = time.time()
        # Our aim is to minimize cost.

        self.Cplex.objective.set_sense(self.Cplex.objective.sense.minimize)
        self.Cplex.set_log_stream(None)
        self.Cplex.set_results_stream(None)
        self.Cplex.set_warning_stream(None)
        self.Cplex.set_error_stream(None)

        if  Constants.Debug:
            self.Cplex.write("mrp%r.lp"%self.EvaluateSolution)

        #name = "mrp_log%r_%r_%r" % ( self.Instance.InstanceName, self.Model, self.DemandScenarioTree.Seed )
        #file = open("/tmp/thesim/CPLEXLog/%s.txt" % self.logfilename, 'w')
        # self.Cplex.set_log_stream(Constants.GetPathCPLEXLog()+"/%s.txt" % self.logfilename) # revise, errors reported in cplex
        # self.Cplex.set_results_stream(Constants.GetPathCPLEXLog()+"/%s.txt" % self.logfilename)
        # self.Cplex.set_warning_stream(Constants.GetPathCPLEXLog()+"/%s.txt" % self.logfilename)
        # self.Cplex.set_error_stream(Constants.GetPathCPLEXLog()+"/%s.txt" % self.logfilename)

        # tune the paramters
        self.Cplex.parameters.timelimit.set(Constants.AlgorithmTimeLimit)
        self.Cplex.parameters.mip.limits.treememory.set(700000000.0)
        self.Cplex.parameters.threads.set(1)
        self.Cplex.parameters.mip.tolerances.integrality.set(0.000000001)#(0.0)
       # self.Cplex.parameters.simplex.tolerances.feasibility.set(0.000000001)
        self.TuneCplexParamter()


        if self.YFixHeuristic:
            self.Cplex.parameters.lpmethod.set(self.Cplex.parameters.lpmethod.values.barrier)
            self.Cplex.parameters.threads.set(1)

        end_modeling = time.time()

        #solve the problem
        #if self.Model == Constants.ModelYFix:
        #    self.Cplex.parameters.benders.strategy.set(3)
        self.Cplex.solve()
        nrvariable= -1
        nrconstraints = -1
        # < or >
        if  not self.EvaluateSolution and not self.EVPI and self.logfilename < "NO":
            nrvariable, nrconstraints = self.ReadNrVariableConstraint(Constants.GetPathCPLEXLog()+"%s.txt" % self.logfilename)

        buildtime = end_modeling - start_time
        solvetime = time.time() - end_modeling

        # Handle the results
        sol = self.Cplex.solution



        #sol.write("SolutionSol")
        if sol.is_primal_feasible():
            if Constants.Debug:
                print("CPLEx Solve Time: %r   CPLEX build time %s  feasible %s cost: %s" % (
                solvetime, buildtime, sol.is_primal_feasible(), sol.get_objective_value()))

            if createsolution:

                Solution = self.CreateMRPSolution(sol, solvetime, nrvariable, nrconstraints)
                #costperscenarios, averagecost, std_devcost = self.ComputeCostPerScenario()

                if Constants.Debug:
                    print("fill solve information......")

                modelname = self.Model
                if self.UseSafetyStock:
                    modelname = modelname + "SS"

                self.SolveInfo = [ self.Instance.InstanceName,
                                   modelname,
                                   Solution.CplexCost,
                                Solution.CplexCost,
                                sol.status[sol.get_status()],
                                buildtime,
                                solvetime,
                                Solution.CplexGap,
                                #sol.progress.get_num_iterations(),
                                #sol.progress.get_num_nodes_processed(),
                                nrvariable,
                                nrconstraints,
                                Solution.InventoryCost,
                                Solution.BackOrderCost,
                                Solution.SetupCost,
                                Solution.VariableCost,
                                Solution.ConsumptionCost,
                                #averagecost,
                                #std_devcost,
                                self.Instance.NrLevel,
                                self.Instance.NrProduct,
                                self.Instance.NrTimeBucket,
                                self.DemandScenarioTree.Seed,
                                self.NrScenario,
                                self.Instance.MaxLeadTime,
                                self.DemandScenarioTree.Distribution ]
            else:
                Solution = None

            return Solution

        else:
            print("No solution available. %r" %self.Cplex.solution.get_status() )
            if Constants.Debug :
                self.Cplex.write("INFEASIBLE.lp")
                self.Cplex.conflict.refine(self.Cplex.conflict.all_constraints())
                conflict = self.Cplex.conflict.get()
                conflicting = [i for i in range(len(conflict)) if conflict[i] == 3]
                groups = self.Cplex.conflict.get_groups(conflicting)
                print("Conflicts: %r"% groups, conflicting)
                for i in groups:
                    (a,((b, c),)) = i
                    print("Constraint %r, %r:"%(c,self.Cplex.linear_constraints.get_names([c])))

    #This function print the scenario of the instance in an excel file
    def PrintScenarioToFile(self):
        writer = pd.ExcelWriter("./Instances/" + self.Instance.InstanceName + "_Scenario.xlsx",
                                        engine='openpyxl')
        for s in self.Scenarios:
            s.PrintScenarioToExcel(writer)
        writer.save()


    def CreateMRPSolution(self, sol, solvetime, nrvariable, nrconstraints):

        scenarioset = self.ScenarioSet
        scenarios = self.Scenarios
        timebucketset = self.Instance.TimeBucketSet
        partialsol = Constants.PrintOnlyFirstStageDecision and (self.Model == Constants.ModelYFix or self.Model == Constants.ModelHeuristicYFix) and not self.EvaluateSolution
        objvalue = sol.get_objective_value()
        array = [self.GetIndexQuantityVariable(p, t, w) for p in self.Instance.ProductSet for t in timebucketset for w
                 in scenarioset]
        solquantity = sol.get_values(array)

        solquantity = Tool.Transform3d(solquantity, self.Instance.NrProduct, len(timebucketset), len(scenarioset))


        # here self.Instance.TimeBucketSet is used because the setups are decided for the complete time horizon in YFix
        array = [self.GetIndexProductionVariable(p, t, w) for p in self.Instance.ProductSet for t in self.Instance.TimeBucketSet for w in scenarioset]
        solproduction = sol.get_values(array)


        solproduction = Tool.Transform3d(solproduction, self.Instance.NrProduct, len(self.Instance.TimeBucketSet), len(scenarioset))


        array = [self.GetIndexInventoryVariable(p, t, w) for p in self.Instance.ProductSet for t in timebucketset for w in scenarioset]
        solinventory = sol.get_values(array)

        solinventory = Tool.Transform3d(solinventory, self.Instance.NrProduct, len(timebucketset), len(scenarioset))

        array = [self.GetIndexBackorderVariable(p, t, w) for p in self.Instance.ProductWithExternalDemand for t in timebucketset for w in scenarioset]
        solbackorder = sol.get_values(array)

        solbackorder = Tool.Transform3d(solbackorder, len(self.Instance.ProductWithExternalDemand), len(timebucketset),
                                        len(scenarioset))

        array = [int(self.GetIndexConsumptionVariable(c[0], c[1], t, w))
                 for c in self.Instance.ConsumptionSet
                 for t in timebucketset
                 for w in scenarioset]

        if len(array)>0:
            solconsumptionval = sol.get_values(array)

        solconsumption = [[[[ -1 for p in self.Instance.ProductSet]
                         for q in self.Instance.ProductSet]
                         for t in timebucketset]
                         for w in scenarioset]

        index = 0
        for p in self.Instance.ProductSet:
            for q in self.Instance.ProductSet:
                for t in timebucketset:
                    for w in scenarioset:
                        if self.Instance.Alternates[p][q]:
                            solconsumption[w][t][p][q] = solconsumptionval[index]
                            index += 1

        solution = Solution(self.Instance, solquantity, solproduction, solinventory, solbackorder, solconsumption, scenarios,
                               self.DemandScenarioTree, partialsolution = partialsol)

        # < or >
        if self.Model < Constants.ModelYQFix:
            self.DemandScenarioTree.FillQuantityToOrder(sol)
            self.DemandScenarioTree.FillQuantityToOrderFromMRPSolution(solution)


        solution.SValue = [[-1 for p in self.Instance.ProductSet] for t in timebucketset]

        solution.FixedQuantity = [[-1 for p in self.Instance.ProductSet] for t in timebucketset]

        solution.CplexCost = objvalue
        solution.CplexGap = 0
        solution.CplexNrVariables = nrvariable
        solution.CplexNrConstraints = nrconstraints
        if not self.EvaluateSolution and not self.YFixHeuristic:
            solution.CplexGap = sol.MIP.get_mip_relative_gap()
            solution.CplexTime = solvetime

        if partialsol:
            solution.DeleteNonFirstStageDecision()

        return solution

    #This function compute the cost per scenario
    def ComputeCostPerScenario(self):
        # Compute the cost per scenario:
        costperscenarion = [sum( self.Cplex.solution.get_values( [self.GetIndexInventoryVariable(p, t, w)] )[0]
                                * self.Instance.InventoryCosts[p] * math.pow( self.Instance.Gamma, t )
                                + self.Cplex.solution.get_values( [self.GetIndexProductionVariable(p, t, w)] )[0]
                                * self.Instance.SetupCosts[p] * math.pow( self.Instance.Gamma, t )
                                for p in self.Instance.ProductSet
                                for t in range(self.Instance.NrTimeBucket ))
                            for w in self.ScenarioSet]


        costperscenarion = [costperscenarion[w]
                            + sum(  self.Cplex.solution.get_values([self.GetIndexBackorderVariable(p, t, w)])[0]
                                     * self.Instance.BackorderCosts[p] * math.pow(self.Instance.Gamma, t)
                                    for p in self.Instance.ProductWithExternalDemand
                                        for t in range(self.Instance.NrTimeBucket -1 ))
                                           for w in self.ScenarioSet ]

        costperscenarion = [costperscenarion[w]
                            + sum(  self.Cplex.solution.get_values([self.GetIndexBackorderVariable(p, self.Instance.NrTimeBucket - 1, w)])[0]
                                    * self.Instance.LostSaleCost[p] * math.pow( self.Instance.Gamma, self.Instance.NrTimeBucket - 1)
                                    for p in self.Instance.ProductWithExternalDemand)
                                                    for w in self.ScenarioSet ]

        Sum = sum(costperscenarion[w] for w in self.ScenarioSet)
        Average = Sum / self.NrScenario
        sumdeviation = sum(math.pow((costperscenarion[s] - Average), 2) for s in self.ScenarioSet)
        std_dev = math.sqrt( (sumdeviation / self.NrScenario ) )


        return costperscenarion, Average, std_dev

    #This function return the upperbound on hte quantities infered from the demand
    @staticmethod
    def GetBigMDemValue(instance, scenarioset, p, totaldemandatt=None, ssgrave=[] ):

        if instance.HasExternalDemand[p]:
            mdem = (sum(max(s.Demands[t][p] for s in scenarioset) for t in instance.TimeBucketSet))

            if totaldemandatt is not None:
                mdem += max(-totaldemandatt[instance.ProductWithExternalDemandIndex[p]], 0)

        else:
            mdem = sum(
                       sum(instance.Requirements[j][k]
                            * MIPSolver.GetBigMDemValue(instance, scenarioset, j)
                            for k in instance.ProductSet
                                    if (instance.Alternates[p][k]
                                        and instance.Requirements[j][k]>0 ))
                       for j in instance.ProductSet )

        if len(ssgrave) > 0:
            mdem = mdem + sum(ssgrave[t][p] for t in instance.TimeBucketSet)

        return mdem

    #This function return the value of the big M variable
    @staticmethod
    def GetBigMValue(instance, scenarioset, p, totaldemandatt=None, ssgrave=[]):
        mdem = MIPSolver.GetBigMDemValue(instance, scenarioset, p, totaldemandatt, ssgrave)

        #compute m based on the capacity of the resource
        if instance.NrResource > 0:
            mres = min(instance.Capacity[k] / instance.ProcessingTime[p][k] if instance.ProcessingTime[p][k] > 0  else Constants.Infinity for k in range( instance.NrResource ) )
        else:
            mres = Constants.Infinity
        m = min([mdem, mres])
        return float(m)

    def ModifyMipForScenarioTree(self, scenariotree):
        self.DemandScenarioTree = scenariotree
        self.DemandScenarioTree.Owner = self
        self.NrScenario = len([n for n in self.DemandScenarioTree.Nodes if len(n.Branches) == 0])
        self.ComputeIndices()
        self.Scenarios = scenariotree.GetAllScenarios(True, self.ExpendFirstNode)
        self.ScenarioSet = range(self.NrScenario)
        # Redefine the flow conservation constraint
        constrainttuples = []
        for p in self.Instance.ProductWithExternalDemand:
            for w in self.ScenarioSet:
                righthandside = -1 * self.Instance.StartingInventories[p]
                for t in self.Instance.TimeBucketSet:
                    righthandside = righthandside + self.Scenarios[w].Demands[t][p]
                    constrnr = self.FlowConstraintNR[w][p][t]
                    constrainttuples.append((constrnr, righthandside))

        self.Cplex.linear_constraints.set_rhs(constrainttuples)
        if self.EVPI:
            #Recompute the value of M
            totaldemandatt = [0 for p in self.Instance.ProductSet]
            self.ModifyBigMForScenario(totaldemandatt)


    def ModifyBigMForScenario(self, totaldemandatt):
        constrainttuples = []
        n = self.NrQuantityVariables
        AlreadyAdded = [[False] * n for w in range(self.GetNrProductionVariable())]

        # Recompute the value of M
        for p in self.Instance.ProductSet:
            for w in self.ScenarioSet:
                for t in self.Instance.TimeBucketSet:
                    indexQ = self.GetIndexQuantityVariable(p, t, w)
                    indexP = self.GetIndexProductionVariable(p, t, w) - self.GetStartProductionVariable()
                    if not AlreadyAdded[indexP][indexQ]:
                        AlreadyAdded[indexP][indexQ] = True
                        column = self.GetIndexProductionVariable(p, t, w)
                        coeff = self.GetBigMValue(self.Instance, self.Scenarios, p, totaldemandatt, self.GivenSSGrave)
                        constrnr = self.BigMConstraintNR[w][p][t]
                        constrainttuples.append((constrnr, column, coeff))
        #print constrainttuples
        #self.Cplex.write("mrp.lp")
        self.Cplex.linear_constraints.set_coefficients(constrainttuples)



    #This function modify the MIP tosolve the scenario tree given in argument.
    #It is assumed that both the initial scenario tree and the new one have a single scenario
    def ModifyMipForScenario(self, demanduptotime, time):

        #Redefine the flow conservation constraint
        constrainttuples=[]
        for p in self.Instance.ProductWithExternalDemand:
           #for w in self.ScenarioSet:
                righthandside = -1 * self.Instance.StartingInventories[p]
                for t in self.Instance.TimeBucketSet:
                    if t< time -1:
                        self.Scenarios[0].Demands[t][p] = demanduptotime[t][p]
                        righthandside = righthandside + self.Scenarios[0].Demands[t][p]
                        constrnr = self.FlowConstraintNR[0][p][t]
                        constrainttuples.append((constrnr, righthandside))
                    if t == time -1:
                        self.Scenarios[0].Demands[t][p] = demanduptotime[t][p]
                        righthandside = 0
                        constrnr = self.FlowConstraintNR[0][p][t]
                        constrainttuples.append((constrnr, righthandside))
                        self.Cplex.linear_constraints.set_rhs(constrainttuples)

        totaldemandattime = [sum(demanduptotime[t][p] for t in range(time))for p in self.Instance.ProductWithExternalDemand]

        knowndemandtuples = [(self.GetIndexKnownDemand(p), sum(demanduptotime[t][p] for t in range(time))) for p in self.Instance.ProductWithExternalDemand]
        self.Cplex.variables.set_lower_bounds(knowndemandtuples)
        self.Cplex.variables.set_upper_bounds(knowndemandtuples)


    #This function modify the MIP to fix the quantities given in argument
    def ModifyMipForFixQuantity(self, givenquanities, fixuntil=-1):
            timeset = self.Instance.TimeBucketSet
            if fixuntil > -1:
                timeset = range(fixuntil)
            # Redefine the flow conservation constraint
            constrainttuples = []

            # Capacity constraint
            for p in self.Instance.ProductSet:
                for t in timeset:
                            righthandside = float(givenquanities[t][p])#
                            constrnr = "L"+self.QuantityConstraintNR[0][p][t]
                            constrainttuples.append((constrnr, righthandside))

            self.Cplex.linear_constraints.set_rhs(constrainttuples)

    def ModifyMipForFixConsumption(self, givenconsumption, fixuntil=-1):
            timeset = self.Instance.TimeBucketSet
            if fixuntil > -1:
                timeset = range(fixuntil)
            # Redefine the flow conservation constraint
            constrainttuples = []

            # Capacity constraint
            for idc in range(len(self.Instance.ConsumptionSet)):
                for t in timeset:
                            righthandside = float(givenconsumption[t][idc])#
                            constrnr = self.ConsumptionConstraintNR[0][idc][t]
                            constrainttuples.append((constrnr, righthandside))

            self.Cplex.linear_constraints.set_rhs(constrainttuples)


    def ModifyMIPForSetup(self, givensetup):
        # setup constraint
        constrainttuples = []
        for p in self.Instance.ProductSet:
            for t in self.Instance.TimeBucketSet:
                tuples = [(self.GetIndexProductionVariable(p, t, w), givensetup[t][p]) for w in self.ScenarioSet]
                self.Cplex.variables.set_lower_bounds(tuples)
                self.Cplex.variables.set_upper_bounds(tuples)
                tuples = [(self.GetIndexQuantityVariable(p, t, w), max((givensetup[t][p]) * self.M, 0.0)) for w in self.ScenarioSet]
                self.Cplex.variables.set_upper_bounds(tuples)
                righthandside = givensetup[t][p]  #
                constrnr = self.SetupConstraint[0][p][t]
                constrainttuples.append((constrnr, righthandside))
        self.Cplex.linear_constraints.set_rhs(constrainttuples)


    def UpdateStartingInventory(self, startinginventories):

        startinginventotytuples = [(self.GetIndexInitialInventoryInRollingHorizon(p, t), startinginventories[t][p])
                                    for p in self.Instance.ProductSet
                                    for t in range(self.Instance.MaimumLeadTime)]
        self.Cplex.variables.set_lower_bounds(startinginventotytuples)
        self.Cplex.variables.set_upper_bounds(startinginventotytuples)


    def UpdateSetup(self, givensetup):

        setuptuples = [(self.GetIndexProductionVariable(p, t, w), float(givensetup[t][p]))
                       for p in self.Instance.ProductSet
                       for t in self.Instance.TimeBucketSet
                       for w in self.ScenarioSet]
        self.Cplex.variables.set_lower_bounds(setuptuples)
        self.Cplex.variables.set_upper_bounds(setuptuples)
