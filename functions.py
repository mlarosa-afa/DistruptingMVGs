import math
import random
import numpy as np
from scipy.stats import invwishart
from docplex.mp.model import Model

#holds the subsets of Lambda
class Lambda:
    def __init__(self, Lambda_dot, evidence_vars, unobserved_vars):
        self.yy = np.delete(Lambda_dot, evidence_vars, 1)
        self.yy = np.delete(self.yy, evidence_vars, 0)
        self.yz = np.delete(Lambda_dot, unobserved_vars, 1)
        self.yz = np.delete(self.yz, evidence_vars, 0)
        self.zy = np.transpose(self.yz)
        self.zz = np.delete(Lambda_dot, unobserved_vars, 1)
        self.zz = np.delete(self.zz, unobserved_vars, 0)

class normal_parameters:
    def __init__(self, Q, vT, c, K,h,g, K_prime,h_prime,u_prime, S_prime, L):
        self.Q, self.vT, self.c, self.K, self.h, self.g, self.K_prime, self.h_prime, self.u_prime, self.S_prime, self.L = Q, vT, c, K,h,g, K_prime,h_prime,u_prime, S_prime, L

#Generates a Positive Definate square matrix of dimention num_dim.
#There may be room for optimization here
def generate_pos_def_matrix(num_dim):
    #runs until matrix is Pos_def
    while True:
        # https://math.stackexchange.com/questions/332456/how-to-make-a-matrix-positive-semidefinite
        random_matrix = np.random.rand(num_dim, num_dim)
        PSD_Random = np.dot(random_matrix, random_matrix.transpose())
        # check to see if PD, if so, continue
        if is_pos_def(PSD_Random):
            break
    return PSD_Random

#Determins if given matrix X is positive definite
def is_pos_def(x):
    return np.all(np.linalg.eigvals(x) > 0)

#Calculate the optimal (max) weights (phi_1 & phi_2)
def  solve_optimal_weights(Q, vT, K_prime, u_prime, NUM_EVIDENCE_VARS, ev_bounds):
    # Solve max KL first
    Dmat = Q
    Dvec = np.transpose(vT)
    bestKL, solution = solveqm(Dmat, Dvec, NUM_EVIDENCE_VARS, ev_bounds=ev_bounds)

    # Solve marginal mode second
    Dmat = -1 * (K_prime)
    Dvec = 2 * np.matmul(K_prime, u_prime)
    bestMM, solution = solveqm(Dmat, Dvec, NUM_EVIDENCE_VARS, ev_bounds=ev_bounds)

    return bestKL, bestMM

def solveqm(Dmat, Dvec, NUM_EVIDENCE, ev_bounds = None, optimality_target = 3):
    qm = Model('DistruptionGBN')
    if (not len(ev_bounds[0]) == NUM_EVIDENCE) or (not len(ev_bounds[1]) == NUM_EVIDENCE):
        raise Exception("Number of Evidence variable passed does not mount Evidence bounds")
    #change to dictonary of cont_vars to edit upper/lower bounds
    z_DV = {}
    for i in range(NUM_EVIDENCE):
        z_DV[i] = qm.continuous_var(name="Z_DV_" + str(i), ub=ev_bounds[0][i], lb=ev_bounds[1][i])  # DV for decision variable

    # Add objective function
    obj_fn = (list(z_DV.values()) @ Dmat @ list(z_DV.values())) + (Dvec @ list(z_DV.values()))
    qm.set_objective("max", obj_fn)

    # This can be improved by including concavity into the decision
    qm.parameters.optimalitytarget.set(optimality_target)
    solutionset = qm.solve()
    return qm.objective_value, solutionset


#Select which variables are evidence given MVG prior and Mean
#Optional Parameters:
# Number of evidence variables to select. Will default to 25% of variables
# evidence variables. list of rows. Will overwrite num of evidence vars if available

def vals_from_priors(MVG_Sigma, MVG_Mu, evidence_vars, evidence):
    unobserved_vars = list(set(list(range(len(MVG_Sigma[1])))) - set(evidence_vars))
    # Is this inverse required?
    Lambda_dot = np.linalg.inv(MVG_Sigma)  #Precision matrix of joint evidence distribution
    eta_dot = np.matmul(Lambda_dot, MVG_Mu)
    Xi_dot = -0.5 * np.matmul(np.matmul(np.transpose(MVG_Mu), Lambda_dot), MVG_Mu) - math.log((2*math.pi)**(MVG_Mu.size/2) * (np.linalg.det(MVG_Sigma) ** 0.5))

    # Lambda Subsets  - Form Block Matrices from Joint Covariance Matrix
    L = Lambda(Lambda_dot, evidence_vars, unobserved_vars)

    Sigma_zz = np.delete(MVG_Sigma, unobserved_vars, 1)
    Sigma_zz = np.delete(Sigma_zz, unobserved_vars, 0)

    #eta Subsets
    eta_y = np.delete(eta_dot, evidence_vars)
    eta_z = np.delete(eta_dot, unobserved_vars)

    # Conditional Distribution
    K = L.yy
    h = eta_y - np.matmul(L.yz, evidence)
    g = Xi_dot + np.matmul(np.transpose(eta_z), evidence) - (0.5 * np.matmul(np.matmul(np.transpose(evidence), L.zz), evidence))

    u_dot = np.matmul(np.linalg.inv(K), h)

    #KL Divergence
    K_prime = L.zz - np.matmul(np.matmul(L.zy,np.linalg.inv(L.yy)),L.yz)
    h_prime = eta_z - np.matmul(L.zy, np.matmul(np.linalg.inv(L.yy), eta_y))

    S_prime = np.linalg.inv(K_prime)
    u_prime = np.matmul(S_prime, h_prime)

    Q = np.matmul(np.matmul(np.transpose(L.yz), np.linalg.inv(K)), L.yz)
    vT = 2 * (np.matmul(np.transpose(u_dot), L.yz) - np.matmul(np.matmul(np.transpose(eta_y), np.linalg.inv(K)), L.yz))
    c = np.matmul(np.matmul(np.transpose(u_dot), K), u_dot) - 2 * np.matmul(np.transpose(eta_y), u_dot) + np.matmul(np.transpose(eta_y), np.matmul(np.linalg.inv(K), eta_y))
    vals = normal_parameters(Q, vT, c, K,h,g, K_prime,h_prime,u_prime, S_prime, L)
    return vals

#given optimals and eigenvalues, calculates concavity
def identify_convavity(rho, Phi_1_opt, Zeta, Phi_2_opt, NUM_EVIDENCE_VARS):
    #identify best constraints
    b_concave = np.inf
    b_convex = -np.inf
    for rho_index in range(1,len(rho)+1):
        for zeta_index in range(1,len(Zeta)+1):
            const = ((Zeta[zeta_index-1] / Phi_2_opt) / ((rho[rho_index-1] / Phi_1_opt) + (Zeta[zeta_index-1] / Phi_2_opt)))
            if rho_index + zeta_index - 1 <= NUM_EVIDENCE_VARS:
                if const < b_concave:
                    b_concave = const
            if rho_index + zeta_index - NUM_EVIDENCE_VARS <= NUM_EVIDENCE_VARS and 1 <= rho_index + zeta_index - NUM_EVIDENCE_VARS:
                if const > b_convex:
                    b_convex = const

    return b_concave, b_convex