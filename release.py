import lgpio

def release_gpio_pins(pins):
    h = lgpio.gpiochip_open(0)
    for pin in pins:
        lgpio.gpio_claim_input(h, pin)
    lgpio.gpiochip_close(h)

release_gpio_pins([26, 16])
