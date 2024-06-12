import numpy as np
import json
import matplotlib.pyplot as plt
from scipy.integrate import simpson
from odeclass import ODE
import pancreas
from scipy.optimize import root_scalar, minimize_scalar
import utils

with open('config.json', 'r') as f:
    standard_params = json.load(f) # reads json file "config.json"

def glucose_penalty(G, Gbar = None, kappa = None, Gmin = None ):
    """
    Calculates penalty given blood glucose.
    p = 1/2 (G - Gbar)**2 + kappa/2 * max(Gmin - G, 0)**2

    Parameters
    ----------
    Gbar : int or float 
        Desired blood glucose
    kappa : int or float 
        Penalty weight
    Gmin : int or float
        Threshold for hypoglycemia
    G : int, float, np.ndarray, list, default: None
        Glucose to evaluate penalty for. If not set, use current state.
    
    Returns
    -------
    p(G) : float or np.ndarray
        Penalty
    """
    # use defaults from config.json
    if Gbar is None:
        Gbar = standard_params["general"].get("Gbar")
    if kappa is None:
        kappa = standard_params["general"].get("kappa")
    if Gmin is None:
        Gmin = standard_params["general"].get("Gmin")
    func = lambda g :  1/2 * (18 * (g - Gbar))**2 + kappa/2 * max((18*(Gmin - g)), 0)**2
    if isinstance(G, (np.ndarray, list)):
        return np.array([func(Gi) for Gi in G])
    return func(G)

def MVP(p, d = 0, uI = 0, uP = 0, HR = None):
    """
    Solves dx = f(x, u, d)

    Parameters
    ----------
    u : int or float 
        Insulin injection rate.
    d : int or float 
        Meal ingestion rate.
    
    Returns
    -------
    dx : numpy array
        Solution to system of differential equations. 
    """
    dD1 = d - p.D1/p.taum
    dD2 = (p.D1 - p.D2)/p.taum
    dIsc = uI/(p.tau1 * p.CI) - p.Isc/p.tau1
    dIp = (p.Isc - p.Ip + uP/p.CI)/p.tau2
    dIeff = -p.p2 * p.Ieff + p.p2 * p.SI * p.Ip
    dG = - (p.GEZI + p.Ieff) * p.G + p.EGP0 + 1000 * p.D2 / (p.VG * p.taum)
    dGsc = (p.G - p.Gsc) / p.tausc

    dx = np.array([dD1, dD2, dIsc, dIp, dIeff, dG, dGsc])
    return dx

def MVP_steadystate(p, G = None, uI = None, uP = 0):
    if uI is None:
        uI = MVP_ssinv(p = p, G = G, uP = uP)
    if G is None:
        G = MVP_ss(p = p, uI = uI, uP = uP)
    Isc = uI / p.CI
    Ip = Isc + uP / p.CI
    Ieff = p.SI * Ip
    x0 = np.array([0, 0, Isc, Ip,Ieff, G, G])
    return x0, uI

def MVP_G_from_u(p, u):
    return p.EGP0/(p.GEZI + p.SI / p.CI * u)

def MVP_ss(p, uI = 0, uP = 0):
    u = uI + uP
    G = MVP_G_from_u(p, u)
    return MVP_steadystate(p, uI = uI, uP = uP, G = G)

def MVP_ssinv(p, G = None, uP = 0):
    if G is None:
        G = p.Gbar
    uI = p.CI/p.SI * (p.EGP0 / G - p.GEZI) - uP
    return uI


def HM(p, d = 0, uI = 0, uP = 0):
    """
    Solves dx = f(x, u, d)

    Parameters
    ----------
    u : int or float 
        Insulin injection rate.
    d : int or float 
        Meal ingestion rate.
    
    Returns
    -------
    dx : numpy array
        Solution to system of differential equations. 
    """
    G = p.Q1/(p.VG * p.BW)
    

    D = 1000 * d/p.MwG

    F01c = min(1, p.G / 4.5) * p.F01 * p.BW
    FR = max(0.003 * (p.G - 9) * p.VG * p.BW, 0) 

    UG = p.D2 / p.taus
    UI = p.S2/p.taus

    dG = (G - p.G)/p.tauig
    dGsc = (p.G - p.Gsc) / p.tausc
    dQ1 = UG - F01c - FR - p.x1 * p.Q1 + p.k12 * p.Q2 + p.BW * p.EGP0 * (1 - p.x3)
    dQ2 = p.Q1 * p.x1 - (p.k12 + p.x2)*p.Q2
    dS1 = uI - p.S1 / p.taus
    dS2 = ((p.S1 - p.S2)/p.taus)
    dI = ((uP + UI) / (p.VI * p.BW) - p.ke * p.I) # Den her kan være wack
    dx1 = p.kb1 * p.I - p.ka1 * p.x1
    dx2 = p.kb2 * p.I - p.ka2 * p.x2
    dx3 = p.kb3 * p.I - p.ka3 * p.x3
    dD1 = p.AG * D - p.D1 / p.taud
    dD2 = (p.D1 - p.D2)/p.taud
    dx = np.array([dG, dGsc, dQ1, dQ2, dS1, dS2, dI, dx1, dx2, dx3, dD1, dD2])
    return dx

def HM_steadystate(p, uP = 0, G = None):
    if G is None:
        G = p.Gbar
    Q1 = G * p.VG * p.BW
    F01c = min(1, G / 4.5) * p.F01 * p.BW
    FR = max(0.003 * (G - 9) * p.VG * p.BW, 0) 

    k1 = p.kb1/p.ka1
    k2 = p.kb2/p.ka2
    k3 = p.kb3/p.ka3

    eq = lambda I0 : -F01c - FR + Q1 * I0 * k1 * (-1 + p.k12 / (p.k12 + k2 * I0)) + p.BW * p.EGP0 * (1 - k3 * I0)
    sol = root_scalar(eq, bracket=[0, 20])
    I = sol.root
    
    uIuP = I * p.VI * p.BW * p.ke
    uI = uIuP - uP
    x1 = k1 * I
    x2 = k2 * I
    x3 = k3 * I

    Q2 = x1 * Q1/(p.k12 + x2)
    S1 = S2 = uI * p.taus
    x0 = np.array([G, G, Q1, Q2, S1, S2, I, x1, x2, x3, 0, 0])
    return x0, uI

def HM_G_from_u(p, u):
    I = u/(p.VI * p.BW * p.ke)
    x1 = p.kb1/p.ka1 * I
    x2 = p.kb2/p.ka2 * I
    x3 = p.kb3/p.ka3 * I

    # Calculate G for any combination of F01c and FR
    G_mat = np.zeros((2,2))
    for k in range(2):
        for c in range(2):
            G_mat[k, c] = (-p.F01 * (1-k) + 0.027 * p.VG * c + p.EGP0 * (1 -x3))/(p.F01 / 4.5 * k + p.VG * ( 0.003 * c + x1  - x1*p.k12 /(p.k12 + x2)))
    # Find valid value
    G_res = np.empty((2,2), dtype=bool)
    G_res[0] = G_mat[0] >= 4.5
    G_res[1] = G_mat[1] <= 4.5
    G_res[:,0] *= G_mat[:,0] <= 9
    G_res[:, 1] *= G_mat[:, 1] >= 9
    G = G_mat[np.where(G_res)][0]
    return G


class Patient(ODE):
    def __init__(self, patient_type, model = "HM", **kwargs):
        self.model = model.upper()
        self.type = patient_type
        defaults = {} #tomt dictionary 
        with open('config.json', 'r') as f:
            data = json.load(f) #læs json-fil
        defaults.update(data["general"]) #tilføj "general" til dictionary(defaults)
        defaults.update(data[self.model]) #tilføj modelegenskaberne til dictionary(defaults)
        defaults.update(kwargs) #tilføj keywordarguments til dictionary(defaults)

        super().__init__(defaults)
        if self.model == "MVP":
            self.f_func = lambda **kwargs: MVP(self,**kwargs) #caller MVP-modellen
        else:
            self.f_func = lambda **kwargs: HM(self,**kwargs) #caller HM-modellen

        if patient_type != 1:
            self.pancreasObj = pancreas.PKPM(patient_type = patient_type, timestep=self.timestep/self.pancreas_n, Gbar=self.Gbar, **kwargs.get("pancreas_param", {}))
        if patient_type != 0:
            self.pumpObj = pancreas.PID(Kp = self.Kp, Td = self.Td, Ti = self.Ti, ybar = self.Gbar, timestep=self.timestep)

    def pump(self, G = None):
        if self.type == 0:
            return 0
        if G is None:
            G == self.Gsc
        return max(0, self.pumpObj.eval(G) + self.us)
    
    def pancreas(self, G):
        if self.type == 1:
            return 0
        u = 0
        for i in range(self.pancreas_n):
            u += self.pancreasObj.eval(G)
        return max(0, u/self.pancreas_n)
        
    def full_reset(self):
        self.reset()
        if self.type != 1:
            self.pancreasObj.reset()
        if self.type != 0:
            self.pumpObj.reset()

    def steadystate(self, uP = 0, G = None):
        if self.model == "HM":
            return HM_steadystate(self, uP=uP, G = G)
        if self.model == "MVP":
            return MVP_steadystate(self, uP=uP, G = G)
        return

    def G_from_u(self, u):
        if self.model == "HM":
            return HM_G_from_u(self, u)
        if self.model == "MVP":
            return MVP_G_from_u(self, u)
        return

    def glucose_penalty(self, G = None):
        """
        Calculates penalty given blood glucose.
        p = 1/2 (G - Gbar)**2 + kappa/2 * max(Gmin - G, 0)**2

        Parameters
        ----------
        Gbar : int or float 
            Desired blood glucose
        kappa : int or float 
            Penalty weight
        Gmin : int or float
            Threshold for hypoglycemia
        G : int, float, np.ndarray, list, default: None
            Glucose to evaluate penalty for. If not set, use current state.
        
        Returns
        -------
        p(G) : float
            Penalty
        """
        if G is None: # If G is not specified, use current G
            G = self.G
        func = lambda g :  1/2 * (18 * (g - self.Gbar))**2 + self.kappa/2 * max((18*(self.Gmin - g)), 0)**2
        if isinstance(G, (np.ndarray, list)):
            return np.array([func(Gi) for Gi in G])
        return func(G)
 
    def simulate(self, ds = None, uIs = None, uPs = None, iterations = None):
        """
        Simulates patient.

        Parameters
        ----------
        ds : numpy array
            Ingestion rate
        u_func : Default = None, int, float, numpy array, list or "PID"
            Specifies insulin injection rate.
            If None; uses steady state insulin rate.
            If "PID"; uses PID controller.
        
        Returns
        -------
        states : numpy array
            State vector in each time step
        u_list : numpy array
            Insulin injection rate for each time step
        """
        if iterations is None:
            iterations = 0
            for arr in [ds, uIs, uPs]:
                if arr is not None:
                    iterations = max(len(arr), iterations)
            if iterations == 0:
                iterations = int(24 * 60 / self.timestep)
        if ds is None: # if no meal is given, set to zero.
            ds = np.zeros(iterations)
            dn = iterations
        else:
            ds = np.array([ds]).flatten()
            dn = len(ds)


        uPs = np.array([uPs]).flatten()
        uIs = np.array([uIs]).flatten()

        def uP_func(i):
            u_panc = self.pancreas(self.G)
            u_arr = uPs[i%len(uPs)]
            if u_arr is None:
                return u_panc
            if np.isnan(u_arr):
                return u_panc
            return u_arr
        
        def uI_func(i):
            u_pump = self.pump(self.Gsc)
            u_arr = uIs[i%len(uIs)]
            if u_arr is None:
                return u_pump
            if np.isnan(u_arr):
                return u_pump
            return u_arr

        info = dict()
        for i in self.state_keys:
            info[i]=np.empty(iterations+1)
            info[i][0]=getattr(self,i)
        info["t"] = self.time_arr(iterations+1)
        info["uP"] = []
        info["uI"] = []
        info["d"] = []
        for i in range(iterations):
            d = ds[i%dn]
            uP = uP_func(i)
            uI = uI_func(i)
            dx = self.f_func(d = d, uI = uI, uP = uP)
            self.euler_step(dx)
            x = utils.ReLU(self.get_state())     
            self.update_state(x)
            for k in self.state_keys:
                info[k][i+1]=getattr(self,k)
            info["uP"].append(uP)
            info["uI"].append(uI)
            info["d"].append(d)
        info["pens"]=self.glucose_penalty(info["G"])
        return info

    def bolus_sim(self, bolus, meal_size, meal_idx = 0, h = 24, plot = False):
        iterations = int(h * 60 / self.timestep)
        ds = np.zeros(iterations)
        us = np.ones(iterations) * self.us
        ds[meal_idx] = meal_size / self.timestep # Ingestion 
        us[0] += bolus / self.timestep
        info = self.simulate(ds = ds, uIs = us)
        Gt = info["G"]
        p = self.glucose_penalty(Gt)
        t = self.time_arr(iterations + 1)/60
        phi = simpson(p, x = t)
        if plot:
            fig, ax = plt.subplots(1,2)
            ax[0].plot(t, p)
            ax[1].plot(t, Gt)
            ax[0].set_xlabel("time(h)")
            ax[1].set_xlabel("time(h)")
            ax[1].set_ylabel("g")

            ax[0].set_title("Penalty Function")
            ax[1].set_title("Blood Glucose")
            plt.show()
        return phi, p, Gt
    
    def best_bolus(self, meal_size, min_bolus = 0, max_bolus = 15000, splits = 10,  h = 24):
        """
        Finds optimals 
        """
        if isinstance(meal_size, (np.ndarray, list)):
            return np.array([self.best_bolus(meal_size=m, h = h) for m in meal_size])
        # broad and rough search for minima
        us = np.linspace(0, max_bolus, splits)
        phis = []
        for u in us:
            phi, _, _ = self.bolus_sim(u, meal_size = meal_size, h = h)
            phis.append(phi)
        # choose u0 where 
        u0 = us[np.argmin(phis)]
        def cost(u):
            phi, _, _ = self.bolus_sim(u, meal_size = meal_size, h = h)
            return phi
        return minimize_scalar(cost, bounds=[u0 - max_bolus/splits, u0 + max_bolus/splits]).x


    def dense_meal_bolus(self, meal_size = 0, min_U = 0, max_U = 100, n = 50, h = 24):
        Us = np.linspace(min_U, max_U, n)
        phi_best = 10**18
        for j, U in enumerate(Us):
            self.full_reset()
            phi, p, Gt = self.bolus_sim(U, meal_size, meal_idx=0, h=h)
            if phi < phi_best:
                p_best = p
                G_best = Gt
                phi_best = phi
                best_u = U
        self.full_reset()
        return best_u, phi_best, p_best, G_best


    def optimal_bolus(self, meal_idx = 0, min_U = 0, max_U = 50, min_meal = 20, max_meal = 150, n = 50, h = 24):
        Us = np.linspace(min_U, max_U, n)
        meals = np.linspace(min_meal, max_meal, n)
        res = np.empty((len(meals), len(Us)))
        for i, d0 in enumerate(meals):
            for j, U in enumerate(Us):
                self.full_reset()
                phi, _, _ = self.bolus_sim(U, d0, meal_idx=meal_idx, h=h)
                res[n - 1 - j ,i] = phi
        best = np.argmin(res, axis=0)
        best_us = [Us[n - 1- i] for i in best]
        return meals, best_us, res


    def statePlot(self,infodict,shape,size,keylist,fonts):

        """ 
        Makes plot of different states. 
        Parameters
        ----------

        infodict: Dictionary of all states/disturbances that could possibly be plotted  from a given simulation

        shape: tuple or list indicating layout of plots ("number of rows", "number of columns")

        size: tuple of list indicating size of figure ("length", "width")

        keylist: A list of lists in row-major order of where to put each plot. 
        
        Returns
        -------

        plots of given states

        Example
        -------
        For example: statePLot( self, info, (1,3), (20,20) , [["D1","D2],["Isc"],["x1","x2","x3"]]
        Creates a plot with  D1 and D2 in one figure, Isc in another and x1, x2 and x3 together in a third figure, in a 1 X 3 layout and 20X20 size.  
        """


        fig,ax=plt.subplots(nrows=shape[0],ncols=shape[1],figsize=size)
        ax=ax.flatten()
        colorlist=["#0B31A5","#D3004C","#107C10"]
        titles={
            "MVP":{
            "D1":["D2","[mmol]"],
            "D2":["D2","[mmol]"],
            "Isc": ["Subc. insulin","[mU/L]"],
            "Ip" : ["Insulin in plasma","[mU/L]"],
            "Ieff": ["Effective insulin","[mU/L]"],
            "G" : ["Blood glucose","[mmol/L]"],
            "Gsc": ["Subc. glucose","[mmol/L]"], 
            "pens": ["Penalty function", " "],
            "uI" : ["Injected Insulin", "[mU/min]"],
            "uP" : ["Insulin from pancreas", "[mU/min]"],
            "d" : ["Carb Ingestion Rate", "[g/min]"]
            },

            "HM": {
            "G" : ["Blood Glucose","[mmol/L]"],
            "Gsc": ["Subc. glucose","[mmol/L]"], 

            "Q1" : ["Main bloods gluc","[mmol]"],
            "Q2" : ["Gluc in peripheral tissue","[mmol]"],
            "S1" : ["Subc. insulin variable 1","[mU]"],
            "S2" : ["Subc. insulin variable 2","[mU]"],
            "I"  : ["Plasma insulin conc.","[mU/L]"],
            "x1": ["I eff. on gluc 1","[1/min]"],
            "x2": ["I eff. on gluc 2","[1/min]"],
            "x3": ["I eff. on gluc 3","[1/min]"],
            "D1": ["Meal Glucose 1","[mmol]"],
            "D2": ["Meal Glucose 2","[mmol]"],
            "Z1": ["Subc. Glucagon","[μg]"],
            "Z2": ["plasma Glucagon","[μg]"],
            "E1": ["Short-term exercise eff.","[min]"],
            "E2": ["Long-term exercise eff.","[min]"],
            "pens": ["Penalty function", " "],
            "uI" : ["Injected Insulin", "[mU/min]"],
            "uP" : ["Insulin from pancreas", "[mU/min]"],
            "d" : ["Carb Ingestion Rate", "[g/min]"]

            }
        }
        
        for i,l in enumerate(keylist):
                title=""
                for c, k in enumerate(l):
                    if c==0:
                        title+=titles[self.model][k][0]
                    elif 0 < c < len(l)-1:
                        title+=", " + titles[self.model][k][0]
                    elif c==len(l)-1:
                        title+=" and "+titles[self.model][k][0]
                    max_l = min(len(infodict["t"]), len(infodict[k]))

                    if k=="G":
                        ax[i].plot(infodict["t"][:max_l]/60, self.Gmin*np.ones(max_l),"--",color="#998F85",label="minimum glucose")
                    ax[i].plot((infodict["t"][:max_l])/60,infodict[k][:max_l],".",label=k,color=colorlist[c])
                    ax[i].set_title(title,fontsize=fonts)
                    ax[i].set_xlabel("Time [h]",fontsize=fonts)
                    ax[i].set_ylabel(titles[self.model][k][1])
                    ax[i].set_xlim(0,infodict["t"][:max_l][-1]/60)
                    ax[i].set_xticks(np.linspace(0,infodict["t"][:max_l][-1]/60,5))
                    ax[i].tick_params(axis='x', labelsize=5)
                ax[i].legend(loc="lower left")
        plt.show()
        fig.tight_layout()
        return

def find_ss(model = "HM", **kwargs): 
    p = Patient(patient_type = 0, model = model, **kwargs)   
    def cost(G):
        _, u = p.pancreasObj.steadystate(G)
        G_res = p.G_from_u(u)
        return G_res-G
    return root_scalar(cost,  bracket= [0.5,20])

def baseline_patient(patient_type = 1, model = "HM", **kwargs):
        Gbar = kwargs.get("Gbar" , find_ss(model, **kwargs).root)
        patient = Patient(patient_type = patient_type, model = model, Gbar = Gbar, **kwargs)
        uP = patient.pancreas(Gbar)
        x0, uI = patient.steadystate(uP = uP, G = Gbar)
        patient.us = max(0,uI)
        patient.update_state(x0) # set to steady state
        for key in patient.state_keys: # also set "x0" values
            setattr(patient, key+"0", getattr(patient, key))
        return patient
