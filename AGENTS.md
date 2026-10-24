Ты помогаешь команде на квантовом хакатоне (трек «Quantum optimization»: реальная задача
с ограничениями, решаемая QAOA и честно сравниваемая с классическими методами).

## Задача

Выбор уровня детализации (LOD) для N=5 объектов 3D-сцены × M=3 уровня под жёсткий
бюджет полигонов кадра. Это задача о ранце с множественным выбором (MCKP).
MCKP → QUBO → QAOA (Qiskit), сравнение с DP (эталон) и Greedy (бейзлайн).

## Обозначения

- Индекс LOD: j=0 — LOD0 (high), j=1 — LOD1, j=2 — LOD2 (low). Массивы имеют форму (N, M).
- Полезность: v[i,j] = S_i * q_j / d_i**alpha, S_i = 4*pi*R_i^2 * importance_i,
  alpha = 1.5, q = (1.0, 0.65, 0.25), нормирована так, что max v = 1.
- Веса в delta-форме: dw[i,j] = ceil((w[i,j] - w[i,M-1]) / block_size), dw[i,M-1] = 0,
  block_size = 5000 треугольников. Бюджет: dW = floor((W_max - W_base) / block_size),
  W_base = sum_i w[i,M-1]. Обычно dW от 8 до 15.
- Ограничения: ровно один LOD на объект; sum_i dw[i, choice[i]] <= dW.

## Кодирование в кубиты

- x[i,j] имеет индекс q = i*M + j (0..14); slack s[k] имеет индекс N*M + k, вес 2^k,
  K = floor(log2(dW)) + 1. При dW ≤ 15 всего 19 кубитов.
- Энергия QUBO (минимизируется):
  E = -sum v*x + A * sum_i (1 - sum_j x[i,j])^2 + B * (sum dw*x + sum 2^k s_k - dW)^2.
  Безопасные штрафы: A = 1.5 * max(v), B = 1.2 * max(v[i,j] - v[i,M-1]).
- Порядок битов как в Qiskit, little-endian: кубит q в bitstring из counts — это bitstring[-1 - q].

## Структура репозитория

(src-layout, uv, Python 3.12)
src/lodq/{config,storage,scene,metrics,meshes,classical,qubo,ising,qaoa,fastsim,
evaluate,experiments,plots,render}.py, scenes/, configs/, assets/lods/, app/, scripts/,
tests/, runs/ (результаты), cache/, figures/.

## Стек

qiskit>=2.0, qiskit-aer, numpy, scipy, pandas, matplotlib, pyyaml, pydantic>=2, pyvista,
streamlit, pytest, ruff. Только Qiskit Primitives V2 (EstimatorV2 / SamplerV2,
StatevectorEstimator / StatevectorSampler). Запрещено: qiskit.execute, V1-примитивы,
qiskit.algorithms, qiskit.opflow. qiskit-optimization — только для перекрёстной проверки.

## Правила кода

- Чистые типизированные функции, numpy-массивы, никакого глобального состояния.
- Случайность только через np.random.default_rng(seed), seed передаётся явно.
- При равенстве вариантов — меньший used, затем лексикографически меньший choice.
- Не меняй контракт выше. Если без этого не обойтись — скажи отдельным пунктом.
- В ответе: полный код каждого файла целиком и команда для запуска тестов.

## Фикстура ловушки

(используется в тестах)
dw = [[8,4,0],[5,3,0],[5,3,0],[4,3,0],[4,3,0]], dW = 10
v  = [[1.00,0.55,0.15],[0.62,0.40,0.10],[0.60,0.38,0.10],[0.20,0.14,0.05],[0.20,0.14,0.05]]
DP: (2,0,0,2,2), V = 1.47, used 10. Greedy: (0,2,2,2,2), V = 1.30, used 8, AR = 0.884.
