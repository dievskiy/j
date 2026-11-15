| Policy | Env | Trials | Mean reward | Run means | Delivery |
|---|---|---|---|---|---|
| reference | rover | 36 | 0.716 ± 0.000 | 0.716 | 100% |
| reference | winch | 39 | 0.777 ± 0.000 | 0.777 | 100% |
| reference | all | 75 | 0.748 ± 0.000 | 0.748 | 100% |
| deepseek | rover | 108 | 0.411 ± 0.064 | 0.422, 0.342, 0.469 | 58% |
| deepseek | winch | 117 | 0.259 ± 0.062 | 0.326, 0.206, 0.244 | 32% |
| deepseek | all | 225 | 0.332 ± 0.053 | 0.372, 0.271, 0.352 | 45% |
| inkling | rover | 108 | 0.099 ± 0.030 | 0.093, 0.132, 0.073 | 15% |
| inkling | winch | 117 | 0.066 ± 0.027 | 0.059, 0.042, 0.095 | 9% |
| inkling | all | 225 | 0.082 ± 0.006 | 0.075, 0.085, 0.085 | 12% |
| do-nothing | rover | 36 | 0.000 ± 0.000 | 0.000 | 0% |
| do-nothing | winch | 39 | 0.000 ± 0.000 | 0.000 | 0% |
| do-nothing | all | 75 | 0.000 ± 0.000 | 0.000 | 0% |

Left out as infrastructure failures: {'eval-deepseek-20261115-005638': 1, 'eval-inkling-20261115-005608': 12, 'eval-inkling-20261115-005656': 8}
