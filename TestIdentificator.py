#This object contains all the information which allow to identify the test
from __future__ import absolute_import, division, print_function

class TestIdentificator( object ):

    # Constructor
    def __init__(self, instancename, model, sampling, nrscenario,method='SDDP', scenarioseed=10000, useevpi=False, nrscenarioforward=1,mipsetting='', sddpsetting='', hybridphsetting='', mllocalsearchsetting=''):
        self.InstanceName = instancename
        self.Model = model
        self.Method = method
        self.ScenarioSampling = sampling
        self.NrScenario = nrscenario
        self.ScenarioSeed = scenarioseed
        self.EVPI = useevpi
        self.MIPSetting = mipsetting
        self.NrScenarioForward = nrscenarioforward
        self.SDDPSetting = sddpsetting
        self.HybridPHSetting = hybridphsetting
        self.MLLocalSearchSetting = mllocalsearchsetting

    def GetAsStringList(self):
        result = [self.InstanceName,
                  self.Model,
                  self.Method,
                  self.ScenarioSampling,
                  self.NrScenario,
                  "%s"%self.ScenarioSeed,
                  "%s"%self.EVPI,
                  "%s"%self.NrScenarioForward,
                  self.MIPSetting,
                  self.SDDPSetting,
                  self.HybridPHSetting,
                  self.MLLocalSearchSetting]
        return result

    def GetAsString(self):
        result = "_".join([self.InstanceName,
                           self.Model,
                           self.Method,
                           self.ScenarioSampling,
                           self.NrScenario,
                           "%s"%self.ScenarioSeed,
                           "%s"%self.EVPI,
                           "%s"%self.NrScenarioForward,
                           self.MIPSetting,
                           self.SDDPSetting,
                           self.HybridPHSetting,
                           self.MLLocalSearchSetting])
        return result
