


from __future__ import absolute_import, division, print_function
from Constants import Constants
from ScenarioTree import ScenarioTree
import time
from MIPSolver import MIPSolver
from SDDP import SDDP
from ProgressiveHedging import ProgressiveHedging
from Hybrid_PH_SDDP import Hybrid_PH_SDDP
from MLLocalSearch import MLLocalSearch
import csv
import datetime
#from DecentralizedMRP import DecentralizedMRP

#This class is a wrapper and it calls the appropriate method depending on the solution
#method provided by the user.
class Solver( object ):

    # Constructor
    def __init__(self, instance, testidentifier, mipsetting, evaluatesol):
        self.Instance = instance
        self.TestIdentifier = testidentifier
        self.ScenarioGeneration = self.TestIdentifier.ScenarioSampling
        self.GivenSetup = []
        self.MIPSetting = mipsetting
        self.UseSS = False
        self.UseSSGrave = False
        self.TestDescription = self.TestIdentifier.GetAsString()
        self.EvaluateSolution = evaluatesol
        self.TreeStructure = self.GetTreeStructure()
        self.SDDPSolver = None


    #return true if the considered model is a two-stage formulation or reduction
    def UseYQFix(self):
        useyqfix = self.TestIdentifier.Model == Constants.ModelYQFix \
                or self.TestIdentifier.Model == Constants.Average \
                or self.TestIdentifier.Model == Constants.AverageSS \
                or self.TestIdentifier.Model == Constants.AverageSSGrave

        return useyqfix

    #This method call the right method
    def Solve(self):
        solution = None
        if self.UseYQFix():
            solution = self.SolveYQFix()

        if self.TestIdentifier.Model == Constants.ModelYFix:
            solution = self.SolveYFix()

        if self.TestIdentifier.Model == Constants.ModelHeuristicYFix:
            solution = self.SolveYFixHeuristic()

        self.PrintSolutionToFile(solution)

        return solution


    def PrintTestResult():
        Parameter = [UseNonAnticipativity, Model, ComputeAverageSolution, ScenarioSeed]
        data = TestIdentifier + SolveInformation + Parameter
        d = datetime.now()
        date = d.strftime('%m_%d_%Y_%H_%M_%S')
        myfile = open(r'./Test/SolveInfo/TestResult_%s.csv' % (GetTestDescription()), 'wb')
        wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
        wr.writerow(data)
        myfile.close()


    def PrintFinalResult():
        data = TestIdentifier + EvaluatorIdentifier + InSampleKPIStat + OutOfSampleTestResult
        d = datetime.now()
        date = d.strftime('%m_%d_%Y_%H_%M_%S')
        if Constants.Debug:
            print
            "print the test result ./Test/TestResult_%s_%s.csv" % (GetTestDescription(), GetEvaluateDescription())
        myfile = open(r'./Test/TestResult_%s_%s.csv' % (GetTestDescription(), GetEvaluateDescription()), 'wb')
        wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
        wr.writerow(data)
        myfile.close()


    def PrintSolutionToFile(self, solution):
        testdescription = self.TestIdentifier.GetAsString()
        if Constants.PrintSolutionFileToExcel:
            solution.PrintToExcel(testdescription)
        else:
            solution.PrintToPickle(testdescription)


    def MRP(self, treestructur=[1, 8, 8, 4, 2, 1, 0], averagescenario=False, recordsolveinfo=False, yfixheuristic=False, warmstart=False):

        scenariotreemodel = self.TestIdentifier.Model

        scenariotree = ScenarioTree(self.Instance, treestructur, self.TestIdentifier.ScenarioSeed,
                                    averagescenariotree=averagescenario,
                                    scenariogenerationmethod=self.ScenarioGeneration,
                                    model=scenariotreemodel,
                                    issymetric=(Constants.MIPBasedOnSymetricTree and scenariotreemodel == Constants.ModelYFix))

        scenarioset = scenariotree.GetAllScenarios(computeindex=False)

        MIPModel = self.TestIdentifier.Model
        if self.TestIdentifier.Model == Constants.Average:
            MIPModel = Constants.ModelYQFix

        mipsolver = MIPSolver(self.Instance, MIPModel, scenariotree, evpi=self.TestIdentifier.EVPI,
                              implicitnonanticipativity=(not self.TestIdentifier.EVPI),
                              evaluatesolution=self.EvaluateSolution,
                              yfixheuristic=yfixheuristic,
                              givensetups=self.GivenSetup,
                              mipsetting=self.TestIdentifier.MIPSetting,
                              warmstart=warmstart,
                              usesafetystock=self.UseSS,
                              usesafetystockgrave=self.UseSSGrave,
                              logfile=self.TestDescription)
        if Constants.Debug:
            self.Instance.PrintInstance()
        if Constants.PrintScenarios:
            mipsolver.PrintScenarioToFile()

        if Constants.Debug:
            print("Start to model in Cplex")
        mipsolver.BuildModel()
        if Constants.Debug:
            print("Start to solve instance %s with Cplex"% self.Instance.InstanceName)




        solution = mipsolver.Solve()
        #solution.Print()
        if recordsolveinfo:
            SolveInformation = mipsolver.SolveInfo

        return solution, mipsolver

    #Solve the two-stage version of the problem
    def SolveYQFix(self):
        tmpmodel = self.TestIdentifier.Model
        start = time.time()

        if Constants.Debug:
            self.Instance.PrintInstance()

        average = False
        nrscenario = int(self.TestIdentifier.NrScenario)
        if Constants.IsDeterministic(self.TestIdentifier.Model):
            average = True
            nrscenario = 1

            if self.TestIdentifier.Model == Constants.AverageSS:
                 self.UseSS = True
            if self.TestIdentifier.Model == Constants.AverageSSGrave:
                 self.UseSSGrave = True
            self.TestIdentifier.Model = Constants.Average

        treestructure = [1, nrscenario] + [1] * (self.Instance.NrTimeBucket - 1) +[ 0 ]
        solution, mipsolver = self.MRP(treestructure, average, recordsolveinfo=True )

        end = time.time()
        solution.TotalTime = end - start

        self.Model = tmpmodel

        return solution


    # Run the method Heuristic YFix: First solve the 2-stage problem to fix the Y variables, then solve the multi-stages problem on large scenario tree.
    def SolveYFixHeuristic(self):

        start = time.time()
        treestructure = [1, 100] + [1] * (self.Instance.NrTimeBucket - 1) + [0]
        self.TestIdentifier.Model = Constants.ModelYQFix
        chosengeneration = self.ScenarioGeneration
        # self.ScenarioGeneration = Constants.RQMC
        solution, mipsolver = self.MRP(treestructure, False, recordsolveinfo=True)
        self.GivenSetup = [[solution.Production[0][t][p] for p in self.Instance.ProductSet] for t in self.Instance.TimeBucketSet]
        if Constants.Debug:
            self.Instance.PrintInstance()

        self.ScenarioGeneration = chosengeneration

        if self.TestIdentifier.Method == "MIP":
            self.TestIdentifier.Model = Constants.ModelYFix
            solution, mipsolver = self.MRP(self.TreeStructure,
                                      averagescenario=False,
                                      recordsolveinfo=True,
                                      yfixheuristic=True)
            self.TestIdentifier.Model = Constants.ModelHeuristicYFix

        if self.TestIdentifier.Method == Constants.SDDP:
             self.TestIdentifier.Model = Constants.ModelHeuristicYFix

             self.SDDPSolver = SDDP(self.Instance, self.TestIdentifier, self.TreeStructure)
             self.SDDPSolver.HasFixedSetup = True
             self.SDDPSolver.HeuristicSetupValue = self.GivenSetup
             self.SDDPSolver.Run()
             if Constants.PrintOnlyFirstStageDecision:
                solution = self.SDDPSolver.CreateSolutionAtFirstStage()
             else:
                 solution = self.SDDPSolver.CreateSolutionOfAllInSampleScenario()
             if Constants.SDDPSaveInExcel:
                self.SDDPSolver.SaveSolver()

        if self.TestIdentifier.Method == Constants.ProgressiveHedging:
            self.TestIdentifier.Model = Constants.ModelHeuristicYFix

            self.TreeStructure = self.GetTreeStructure()

            self.ProgressiveHedging = ProgressiveHedging(self.Instance, self.TestIdentifier, self.TreeStructure, givensetup=self.GivenSetup)
            solution = self.ProgressiveHedging.Run()


        end = time.time()
        solution.TotalTime = end - start
        return solution


    #This function solve the multi-stage stochastic optimization model
    def SolveYFix(self):
        start = time.time()

        if Constants.Debug:
            self.Instance.PrintInstance()

        methodtemp = self.TestIdentifier.Method
        if self.TestIdentifier.Method == "MIP":
            # 很奇怪要用这个 structure
            treestructure = [1, 200] + [1] * (self.Instance.NrTimeBucket - 1) + [0] # python 的列表可以直接通过相加扩容
            # self.TestIdentifier.Model = Constants.ModelYQFix # 似乎仍然是 YQFix
            chosengeneration = self.TestIdentifier.ScenarioSampling
            # self.ScenarioGeneration = "RQMC" 
            # 看看他如何从这个 treestructure 构造 scenario
            solution, mipsolver = self.MRP(treestructure, False, recordsolveinfo=True)
            self.GivenSetup = [[solution.Production[0][t][p] for p in self.Instance.ProductSet] for t in self.Instance.TimeBucketSet]
            self.ScenarioGeneration = chosengeneration
            self.TestIdentifier.Model = Constants.ModelYFix
            self.TestIdentifier.Method = methodtemp

        if self.TestIdentifier.Method == "MIP":

            self.TreeStructure = self.GetTreeStructure()
            solution, mipsolver = self.MRP(self.TreeStructure, averagescenario=False, recordsolveinfo=True, warmstart=True)

        if self.TestIdentifier.Method == Constants.SDDP:
             self.TreeStructure = self.GetTreeStructure()
             self.SDDPSolver = SDDP(self.Instance, self.TestIdentifier, self.TreeStructure)
             self.SDDPSolver.HeuristicSetupValue = self.GivenSetup
             self.SDDPSolver.Run()
             if Constants.PrintOnlyFirstStageDecision:
                solution = self.SDDPSolver.CreateSolutionAtFirstStage()
             else:
                 solution = self.SDDPSolver.CreateSolutionOfAllInSampleScenario()
             if Constants.SDDPSaveInExcel:
                self.SDDPSolver.SaveSolver()

        if self.TestIdentifier.Method == Constants.ProgressiveHedging:
            self.TreeStructure = self.GetTreeStructure()

            self.ProgressiveHedging = ProgressiveHedging(self.Instance, self.TestIdentifier, self.TreeStructure)
            solution = self.ProgressiveHedging.Run()


        if self.TestIdentifier.Method == Constants.Hybrid:
            self.TreeStructure = self.GetTreeStructure()

            self.Hybrid = Hybrid_PH_SDDP(self.Instance, self.TestIdentifier, self.TreeStructure, self)
            self.Hybrid.Run()
            if Constants.PrintOnlyFirstStageDecision:
                solution = self.Hybrid.SDDPSolver.CreateSolutionAtFirstStage()
            else:
                 solution = self.Hybrid.SDDPSolver.CreateSolutionOfAllInSampleScenario()

            self.SDDPSolver = self.Hybrid.SDDPSolver
            if Constants.SDDPSaveInExcel:
                self.SDDPSolver.SaveSolver()
        if self.TestIdentifier.Method == Constants.MLLocalSearch:
            self.MLLocalSearch = MLLocalSearch(self.Instance, self.TestIdentifier, self.TreeStructure, self)

            solution = self.MLLocalSearch.Run()
            self.SDDPSolver = self.MLLocalSearch.SDDPSolver
            if Constants.PrintOnlyFirstStageDecision:
                solution = self.SDDPSolver.CreateSolutionAtFirstStage()
            else:
                solution = self.SDDPSolver.CreateSolutionOfAllInSampleScenario()

            solution.MLLocalSearchLB =  self.MLLocalSearch.MLLocalSearchLB
            solution.MLLocalSearchTimeBestSol = self.MLLocalSearch.MLLocalSearchTimeBestSol

            if Constants.SDDPSaveInExcel:
                self.SDDPSolver.SaveSolver()

        end = time.time()
        solution.TotalTime = end - start
        return solution


    #Define the tree  structur do be used
    def GetTreeStructure(self):
        treestructure = []
        nrtimebucketconsidered = self.Instance.NrTimeBucket
        if self.TestIdentifier.ScenarioSampling == Constants.RollingHorizon:
            nrtimebucketconsidered = self.Instance.MaxLeadTime + self.TestIdentifier.TimeHorizon

        if Constants.IsDeterministic(self.TestIdentifier.Model):
            treestructure = [1, 1] + [1] * (nrtimebucketconsidered - 1) + [0]

        if self.TestIdentifier.Model == Constants.ModelYQFix:
            treestructure = [1, int(self.TestIdentifier.NrScenario)] + [1] * (nrtimebucketconsidered - 1) + [0]

        if self.TestIdentifier.Model == Constants.ModelYFix or self.TestIdentifier.Model == Constants.ModelHeuristicYFix:
            treestructure = [1, 1] + [1] * (nrtimebucketconsidered - 1) + [0]
            stochasticparttreestructure = [1, 1] + [1] * (nrtimebucketconsidered - 1) + [0]


            nrtimebucketstochastic = self.Instance.NrTimeBucket \
                                     - self.Instance.NrTimeBucketWithoutUncertaintyBefore \
                                     - self.Instance.NrTimeBucketWithoutUncertaintyAfter

            if self.TestIdentifier.NrScenario == "4":
                if nrtimebucketstochastic == 1:
                    stochasticparttreestructure = [4]
                if nrtimebucketstochastic == 2:
                    stochasticparttreestructure = [4, 1]
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [2, 2, 1]
                if nrtimebucketstochastic == 4:
                    stochasticparttreestructure = [2, 2, 1, 1]
                if nrtimebucketstochastic == 5:
                    stochasticparttreestructure = [2, 2, 1, 1, 1]
                if nrtimebucketstochastic == 6:
                    stochasticparttreestructure = [2, 2, 1, 1, 1, 1]
                if nrtimebucketstochastic == 7:
                    stochasticparttreestructure = [2, 2, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 8:
                    stochasticparttreestructure = [2, 2, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 9:
                    stochasticparttreestructure = [2, 2, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 10:
                    stochasticparttreestructure = [4, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 11:
                    stochasticparttreestructure = [4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 12:
                    stochasticparttreestructure = [4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 13:
                    stochasticparttreestructure = [4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 14:
                    stochasticparttreestructure = [4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

            if self.TestIdentifier.NrScenario == "all20":
                stochasticparttreestructure = [20]*nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all50":
                stochasticparttreestructure = [50] * nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all100":
                stochasticparttreestructure = [100] * nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all10":
                stochasticparttreestructure = [10]*nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all5":
                stochasticparttreestructure = [5]*nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all4":
                stochasticparttreestructure = [4] * nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all1":
                stochasticparttreestructure = [1] * nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "all2":
                stochasticparttreestructure = [2] * nrtimebucketstochastic


            if self.TestIdentifier.NrScenario == "DependOnH":
                if nrtimebucketstochastic == 1:
                    stochasticparttreestructure = [100] * nrtimebucketstochastic
                if nrtimebucketstochastic == 2:
                    stochasticparttreestructure = [100] * nrtimebucketstochastic
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [100] * nrtimebucketstochastic
                if nrtimebucketstochastic == 4:
                    stochasticparttreestructure = [50] * nrtimebucketstochastic
                if nrtimebucketstochastic == 5:
                    stochasticparttreestructure = [50] * nrtimebucketstochastic
                if nrtimebucketstochastic == 6:
                    stochasticparttreestructure = [20] * nrtimebucketstochastic
                if nrtimebucketstochastic == 7:
                    stochasticparttreestructure = [20] * nrtimebucketstochastic
                if nrtimebucketstochastic == 8:
                    stochasticparttreestructure = [5] * nrtimebucketstochastic
                if nrtimebucketstochastic == 9:
                    stochasticparttreestructure = [5] * nrtimebucketstochastic
                if nrtimebucketstochastic == 10:
                    stochasticparttreestructure = [5] * nrtimebucketstochastic

            if self.TestIdentifier.NrScenario == "6400b":
                if nrtimebucketstochastic == 1:
                    stochasticparttreestructure = [6400]
                if nrtimebucketstochastic == 2:
                    stochasticparttreestructure = [100, 64]
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [50, 32, 4]
                if nrtimebucketstochastic == 4:
                    stochasticparttreestructure = [50, 8, 4, 4]
                if nrtimebucketstochastic == 5:
                    stochasticparttreestructure = [50, 8, 4, 4, 1]
                if nrtimebucketstochastic == 6:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1]
                if nrtimebucketstochastic == 7:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1]
                if nrtimebucketstochastic == 8:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1]
                if nrtimebucketstochastic == 9:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 10:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 11:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 12:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 13:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 14:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                if nrtimebucketstochastic == 15:
                    stochasticparttreestructure = [50, 8, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

            if self.TestIdentifier.NrScenario == "1000":
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [25, 10, 4]
                if nrtimebucketstochastic >= 4:
                    stochasticparttreestructure = [25, 10, 2, 2] + [1]*(nrtimebucketstochastic-3)

            if self.TestIdentifier.NrScenario == "50-50-10-5":
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [50, 50, 10]
                if nrtimebucketstochastic >= 4:
                    stochasticparttreestructure = [50, 50, 10] + [5]*(nrtimebucketstochastic-3)

            if self.TestIdentifier.NrScenario == "50-50-10":
                stochasticparttreestructure = [50, 50] + [10] * (nrtimebucketstochastic - 2)

            if self.TestIdentifier.NrScenario == "50-10-10-5":
                if nrtimebucketstochastic == 3:
                    stochasticparttreestructure = [50, 10, 10]
                if nrtimebucketstochastic >= 4:
                    stochasticparttreestructure = [50, 10, 10] + [5] * (nrtimebucketstochastic - 3)

            #if not self.TestIdentifier.PolicyGeneration == Constants.RollingHorizon:
            k = 0
            for i in range(self.Instance.NrTimeBucketWithoutUncertaintyBefore + 1,
                               nrtimebucketconsidered  - self.Instance.NrTimeBucketWithoutUncertaintyAfter + 1):
                    treestructure[i] = stochasticparttreestructure[k]
                    k += 1
            #else:
            #    treestructure = stochasticparttreestructure
        return treestructure
