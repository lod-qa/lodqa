"""NumPy statevector simulation for diagonal-cost QAOA circuits."""

from collections.abc import MutableSequence

import numpy as np
from scipy.optimize import minimize


def _energy_vector(energies: np.ndarray, n: int) -> np.ndarray:
    values = np.asarray(energies, dtype=np.float64)
    if values.shape != (1 << n,):
        raise ValueError(f"energies must have shape ({1 << n},), got {values.shape}")
    if not np.all(np.isfinite(values)):
        raise ValueError("energies must contain only finite values")
    return values


def _angles(gammas: np.ndarray, betas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gamma_values = np.asarray(gammas, dtype=np.float64)
    beta_values = np.asarray(betas, dtype=np.float64)
    if gamma_values.ndim != 1 or gamma_values.size == 0 or beta_values.shape != gamma_values.shape:
        raise ValueError(
            "gammas and betas must be non-empty 1-D arrays of the same shape, got "
            f"{gamma_values.shape} and {beta_values.shape}"
        )
    if not np.all(np.isfinite(gamma_values)) or not np.all(np.isfinite(beta_values)):
        raise ValueError("gammas and betas must contain only finite values")
    return gamma_values, beta_values


def qaoa_state(
    energies_scaled: np.ndarray,
    gammas: np.ndarray,
    betas: np.ndarray,
    n: int,
) -> np.ndarray:
    """Return the QAOA state using Qiskit's phase-then-X-mixer conventions."""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    energies = _energy_vector(energies_scaled, n)
    gamma_values, beta_values = _angles(gammas, betas)

    state = np.full(1 << n, 1.0 / np.sqrt(1 << n), dtype=np.complex128)
    for gamma, beta in zip(gamma_values, beta_values, strict=True):
        state *= np.exp(-1j * gamma * energies)
        cosine, sine = np.cos(beta), np.sin(beta)
        mixer = np.array(
            [[cosine, -1j * sine], [-1j * sine, cosine]],
            dtype=np.complex128,
        )
        for qubit in range(n):
            tensor = state.reshape(1 << (n - qubit - 1), 2, 1 << qubit)
            state = np.einsum("ab,ibc->iac", mixer, tensor, optimize=False).reshape(-1)
    return state


def expectation(psi: np.ndarray, energies: np.ndarray) -> float:
    state = np.asarray(psi, dtype=np.complex128)
    values = np.asarray(energies, dtype=np.float64)
    if state.ndim != 1 or values.shape != state.shape or state.size == 0:
        raise ValueError(
            "psi and energies must be non-empty 1-D arrays with the same shape, got "
            f"{state.shape} and {values.shape}"
        )
    if not np.all(np.isfinite(state)) or not np.all(np.isfinite(values)):
        raise ValueError("psi and energies must contain only finite values")
    return float(np.dot(np.abs(state) ** 2, values))


def probabilities(psi: np.ndarray) -> np.ndarray:
    state = np.asarray(psi, dtype=np.complex128)
    if state.ndim != 1 or state.size == 0 or state.size & (state.size - 1):
        raise ValueError("psi must be a non-empty 1-D statevector of power-of-two length")
    if not np.all(np.isfinite(state)):
        raise ValueError("psi must contain only finite values")
    return np.asarray(np.abs(state) ** 2, dtype=np.float64)


def optimize_fast(
    energies: np.ndarray,
    n: int,
    p: int,
    seed: int,
    n_starts: int = 20,
    maxiter: int = 500,
    *,
    warm_start: tuple[np.ndarray, np.ndarray] | None = None,
    history: MutableSequence[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Minimize the exact QAOA energy using deterministic seeded COBYLA starts."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if p < 1:
        raise ValueError(f"p must be >= 1, got {p}")
    if n_starts < 1:
        raise ValueError(f"n_starts must be >= 1, got {n_starts}")
    if maxiter < 1:
        raise ValueError(f"maxiter must be >= 1, got {maxiter}")
    energy_values = _energy_vector(energies, n)
    if warm_start is None:
        t = (np.arange(p, dtype=np.float64) + 0.5) / p
        initial_gammas, initial_betas = t * 0.75, -(1.0 - t) * 0.75
    else:
        initial_gammas, initial_betas = _angles(*warm_start)
        if initial_gammas.shape != (p,):
            raise ValueError(f"warm_start angles must have shape ({p},)")

    starts = [np.concatenate((initial_gammas, initial_betas))]
    rng = np.random.default_rng(seed)
    for _ in range(n_starts - 1):
        starts.append(np.concatenate((rng.uniform(0.0, np.pi, p), rng.uniform(-np.pi / 2, 0.0, p))))

    evaluation_history = history if history is not None else []

    def objective(x: np.ndarray) -> float:
        gammas, betas = x[:p], x[p:]
        value = expectation(qaoa_state(energy_values, gammas, betas, n), energy_values)
        evaluation_history.append(value)
        return value

    best_x: np.ndarray | None = None
    best_value = np.inf
    for initial in starts:
        result = minimize(
            objective,
            initial,
            method="COBYLA",
            options={"maxiter": maxiter, "rhobeg": 0.3},
        )
        if float(result.fun) < best_value:
            best_x, best_value = np.asarray(result.x, dtype=np.float64), float(result.fun)

    if best_x is None:
        raise RuntimeError("COBYLA did not produce an optimization result")
    return best_x[:p].copy(), best_x[p:].copy(), best_value


def landscape_p1(energies: np.ndarray, n: int, grid: int = 60) -> np.ndarray:
    """Evaluate a quadratic Hamiltonian's p=1 landscape using its diagonal energies."""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if grid < 1:
        raise ValueError(f"grid must be >= 1, got {grid}")
    energy_values = _energy_vector(energies, n)
    gammas = np.linspace(0.0, np.pi, grid)
    betas = np.linspace(0.0, np.pi / 2, grid)
    landscape = np.empty((grid, grid), dtype=np.float64)
    constant = float(energy_values[0])
    linear = np.array(
        [energy_values[1 << qubit] - constant for qubit in range(n)],
        dtype=np.float64,
    )
    quadratic = np.zeros((n, n), dtype=np.float64)
    for first in range(n):
        for second in range(first + 1, n):
            quadratic[first, second] = (
                energy_values[(1 << first) | (1 << second)]
                - constant
                - linear[first]
                - linear[second]
            )
            quadratic[second, first] = quadratic[first, second]

    for gamma_index, gamma in enumerate(gammas):
        single_y = np.zeros(n, dtype=np.float64)
        pair_yz = np.zeros((n, n), dtype=np.float64)
        pair_yy = np.zeros((n, n), dtype=np.float64)
        for first in range(n):
            first_coeffs = -quadratic[first].copy()
            first_coeffs[first] = 0.0
            single_y[first] = _phase_average(gamma, -linear[first], first_coeffs).imag
            for second in range(n):
                if first != second:
                    pair_yz[first, second] = _phase_average(
                        gamma,
                        -linear[first],
                        first_coeffs,
                        weighted_qubit=second,
                    ).imag
        for first in range(n):
            for second in range(first + 1, n):
                first_coeffs = -(quadratic[first] + quadratic[second])
                first_coeffs[first] = first_coeffs[second] = 0.0
                second_coeffs = quadratic[second] - quadratic[first]
                second_coeffs[first] = second_coeffs[second] = 0.0
                phase_00_11 = _phase_average(
                    gamma,
                    -linear[first] - linear[second] - quadratic[first, second],
                    first_coeffs,
                ).real
                phase_01_10 = _phase_average(
                    gamma,
                    linear[second] - linear[first],
                    second_coeffs,
                ).real
                pair_yy[first, second] = pair_yy[second, first] = (phase_01_10 - phase_00_11) / 2

        cosine = np.cos(2 * betas)
        sine = np.sin(2 * betas)
        values = np.full(grid, constant, dtype=np.float64)
        for qubit in range(n):
            values += linear[qubit] * (1 - sine * single_y[qubit]) / 2
        for first in range(n):
            for second in range(first + 1, n):
                zz = (
                    cosine * sine * (pair_yz[first, second] + pair_yz[second, first])
                    + sine**2 * pair_yy[first, second]
                )
                values += (
                    quadratic[first, second]
                    * (1 - sine * single_y[first] - sine * single_y[second] + zz)
                    / 4
                )
        landscape[gamma_index] = values
    return landscape


def _phase_average(
    gamma: float,
    offset: float,
    coefficients: np.ndarray,
    weighted_qubit: int | None = None,
) -> complex:
    phases = np.exp(1j * gamma * coefficients)
    factors = (1 + phases) / 2
    if weighted_qubit is not None:
        factors[weighted_qubit] = (1 - phases[weighted_qubit]) / 2
    return complex(np.exp(1j * gamma * offset) * np.prod(factors))
