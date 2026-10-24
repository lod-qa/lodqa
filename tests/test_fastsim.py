import numpy as np
import pytest
from qiskit_aer import AerSimulator

from lodq.fastsim import expectation, landscape_p1, optimize_fast, probabilities, qaoa_state
from lodq.ising import qubo_to_ising
from lodq.metrics import Problem, toy_trap_problem
from lodq.qaoa import (
    assemble_values,
    build_qaoa_circuit,
    make_estimator,
    normalize_operator,
    run_qaoa,
    toy_problem,
)
from lodq.qubo import Qubo, all_energies, build_qubo


def make_toy_qubo() -> Qubo:
    v, dw, dW = toy_problem()
    return build_qubo(v, dw, dW, A=1.5 * v.max(), B=1.2 * (v - v[:, -1:]).max())


def make_trap_qubo(problem: Problem) -> Qubo:
    return build_qubo(problem.v, problem.dw, problem.dW, A=1.5, B=1.02)


@pytest.fixture(params=["toy", "trap"])
def qubo(request: pytest.FixtureRequest) -> Qubo:
    if request.param == "toy":
        return make_toy_qubo()
    return make_trap_qubo(toy_trap_problem())


@pytest.mark.parametrize("seed", [3, 11, 42])
def test_qaoa_state_matches_aer_expectation_and_distribution(qubo: Qubo, seed: int) -> None:
    rng = np.random.default_rng(seed)
    p = 2
    gammas = rng.uniform(0.0, np.pi, p)
    betas = rng.uniform(-np.pi / 2, 0.0, p)
    op, const = qubo_to_ising(qubo)
    cost_op, scale = normalize_operator(op)
    circuit = build_qaoa_circuit(cost_op, p)
    values = assemble_values(circuit, gammas, betas)
    aer_circuit = circuit.assign_parameters(values)
    aer_circuit.save_statevector()
    aer_state = (
        AerSimulator(method="statevector").run(aer_circuit, shots=1).result().get_statevector()
    )
    energies_scaled = all_energies(qubo) / scale

    state = qaoa_state(energies_scaled, gammas, betas, qubo.n)

    assert expectation(state, energies_scaled) == pytest.approx(
        float(
            make_estimator("aer", seed=seed).run([(circuit, cost_op, values)]).result()[0].data.evs
        )
        + const / scale,
        abs=1e-6,
    )
    total_variation = 0.5 * np.abs(probabilities(state) - np.abs(aer_state) ** 2).sum()
    assert total_variation < 1e-6


def test_qaoa_state_has_uniform_distribution_at_zero_angles() -> None:
    energies = np.arange(8, dtype=np.float64)

    state = qaoa_state(energies, np.zeros(1), np.zeros(1), n=3)

    np.testing.assert_allclose(probabilities(state), np.full(8, 1 / 8), atol=1e-15)


def test_optimize_fast_tracks_objective_history_and_is_reproducible() -> None:
    qubo = make_toy_qubo()
    energies = all_energies(qubo)
    history: list[float] = []

    gammas, betas, best = optimize_fast(
        energies, qubo.n, p=1, seed=5, n_starts=2, maxiter=60, history=history
    )
    again = optimize_fast(energies, qubo.n, p=1, seed=5, n_starts=2, maxiter=60)

    assert gammas.shape == betas.shape == (1,)
    assert history
    assert best == pytest.approx(min(history))
    np.testing.assert_array_equal(gammas, again[0])
    np.testing.assert_array_equal(betas, again[1])
    assert best == pytest.approx(again[2])


def test_run_qaoa_fast_backend_uses_numpy_optimizer_and_aer_sampling() -> None:
    qubo = make_toy_qubo()

    result = run_qaoa(qubo, p=1, seed=0, n_starts=1, maxiter=60, shots=256, backend="fastsim")

    assert result.backend == "fastsim"
    assert result.energy_history[-1] == pytest.approx(result.best_expectation)
    assert sum(result.counts.values()) == 256
    assert result.best_expectation < result.energy_history[0]


def test_landscape_p1_has_requested_grid_shape() -> None:
    qubo = make_toy_qubo()
    energies = all_energies(qubo)

    values = landscape_p1(energies, qubo.n, grid=5)

    assert values.shape == (5, 5)
    assert np.all(np.isfinite(values))
    for gamma_index, gamma in enumerate(np.linspace(0.0, np.pi, 5)):
        for beta_index, beta in enumerate(np.linspace(0.0, np.pi / 2, 5)):
            state = qaoa_state(energies, np.array([gamma]), np.array([beta]), qubo.n)
            assert values[gamma_index, beta_index] == pytest.approx(
                expectation(state, energies), abs=1e-12
            )


def test_landscape_p1_matches_statevector_for_19_qubits() -> None:
    qubo = make_trap_qubo(toy_trap_problem())
    energies = all_energies(qubo)
    values = landscape_p1(energies, qubo.n, grid=3)
    gammas = np.linspace(0.0, np.pi, 3)
    betas = np.linspace(0.0, np.pi / 2, 3)

    for gamma_index, gamma in enumerate(gammas):
        for beta_index, beta in enumerate(betas):
            state = qaoa_state(energies, np.array([gamma]), np.array([beta]), qubo.n)
            assert values[gamma_index, beta_index] == pytest.approx(
                expectation(state, energies), abs=1e-8
            )


@pytest.mark.parametrize(
    ("energies", "gammas", "betas", "n"),
    [
        (np.zeros(3), np.ones(1), np.ones(1), 1),
        (np.zeros(4), np.ones(1), np.ones(2), 2),
        (np.full(4, np.nan), np.ones(1), np.ones(1), 2),
    ],
)
def test_qaoa_state_rejects_invalid_inputs(
    energies: np.ndarray, gammas: np.ndarray, betas: np.ndarray, n: int
) -> None:
    with pytest.raises(ValueError):
        qaoa_state(energies, gammas, betas, n)


def test_landscape_rejects_invalid_grid() -> None:
    with pytest.raises(ValueError, match="grid"):
        landscape_p1(np.zeros(2), n=1, grid=0)
