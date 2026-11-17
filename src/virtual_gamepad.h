#pragma once

#include <SDL3/SDL.h>

namespace frontend {

// Uses SDL's joystick backend so automated input passes through normal gamepad mapping.
class VirtualGamepad {
public:
    VirtualGamepad() {
        SDL_VirtualJoystickDesc description;
        SDL_INIT_INTERFACE(&description);
        description.type = SDL_JOYSTICK_TYPE_GAMEPAD;
        description.naxes = SDL_GAMEPAD_AXIS_COUNT;
        description.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
        description.name = "3D Land test controller";
        id = SDL_AttachVirtualJoystick(&description);
        if (id) joystick = SDL_OpenJoystick(id);
    }

    ~VirtualGamepad() {
        if (joystick) SDL_CloseJoystick(joystick);
        if (id) SDL_DetachVirtualJoystick(id);
    }

    VirtualGamepad(const VirtualGamepad &) = delete;
    VirtualGamepad &operator=(const VirtualGamepad &) = delete;
    explicit operator bool() const { return joystick != nullptr; }
    SDL_JoystickID instance() const { return id; }

    bool button(SDL_GamepadButton control, bool down) const {
        return SDL_SetJoystickVirtualButton(joystick, int(control), down);
    }

    bool axis(SDL_GamepadAxis control, int16_t value) const {
        return SDL_SetJoystickVirtualAxis(joystick, int(control), value);
    }

private:
    SDL_Joystick *joystick = nullptr;
    SDL_JoystickID id = 0;
};

} // namespace frontend
