import csn_matplotlib
import matplotlib.pyplot as plt

fig, (ax_time, ax_phase) = plt.subplots(1, 2, figsize=(12, 4))


# prey_predator.py, inside a function: each parameter is a slider (progress is optional - the bar)
def draw(lambda_b=1, lambda_r=4, b_e=0.5, r_e=0.25,  # Model params
         b_0=1.0, r_0=0.1,  # Init conditions
         start_simulation_time=0, final_simulation_time=20, steps=500,  # Time discretasation
         progress=None):

    # Var initialisation, creating 0 arrays
    b_values = [0] * (steps + 1)
    r_values = [0] * (steps + 1)
    t_values = [0] * (steps + 1)


    step_size = final_simulation_time / steps

    # Populate the time scale based on the step size
    for i in range(steps + 1):
        if i == 0:
            t_values[0] = start_simulation_time
            continue

        t_values[i] = t_values[i - 1] + step_size


    # Calculate the populations using explicit Euler
    for i in range(steps):
        if i == 0: # In the start of the list, set initial conditions
            b_values[0] = b_0
            r_values[0] = r_0

        b = b_values[i]
        r = r_values[i]

        b_dot = lambda_b * b * (1 - r / r_e)
        r_dot = lambda_r * r * (b / b_e - 1)

        b_values[i + 1] = b + step_size * b_dot
        r_values[i + 1] = r + step_size * r_dot

        if progress and i % 20000 == 0:
            progress(i, steps)



    # Plot the results

    ax_time.plot(t_values, b_values, "o", label="prey")
    ax_time.plot(t_values, r_values, "o", label="predator")
    ax_time.set_xlabel("time")
    ax_time.set_ylabel("population")
    ax_time.set_title(f"Predator - prey populations over time, steps: {steps}")
    ax_time.legend()

    ax_phase.plot(b_values, r_values)
    ax_phase.set_xlabel("prey population")
    ax_phase.set_ylabel("predator population")
    ax_phase.set_title(f"Predator - prey populations phase diagram, steps: {steps}")


csn_matplotlib.sliders(draw, lambda_b=(0.1, 5), lambda_r=(0.1, 10), b_e=(0.05, 2), r_e=(0.02, 1),
                       b_0=(0.01, 3), r_0=(0.01, 1, 'log'),
                       start_simulation_time=(0, 50), final_simulation_time=(1, 100), steps=(10, 1_000_000, 'log'))
plt.show()
