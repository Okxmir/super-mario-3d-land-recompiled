#pragma once

#include <SDL3/SDL.h>
#include <windows.h>
#include <commctrl.h>
#include <dwmapi.h>

// The Windows SDK defines this name as a macro. The SDL layout uses it as a local variable.
#undef small

#include "frontend/settings.h"
#include "log.h"
#include "video/pica.h"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "dwmapi.lib")

namespace frontend {

class ResolutionMenu {
public:
    ResolutionMenu(SDL_Window *window, Settings &settings) : settings_(settings) {
        hwnd_ = static_cast<HWND>(SDL_GetPointerProperty(
            SDL_GetWindowProperties(window), SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr));
        if (!hwnd_) return;

        bar_ = CreateMenu();
        choices_ = CreatePopupMenu();
        if (!bar_ || !choices_ || !AppendMenuW(bar_, MF_POPUP, reinterpret_cast<UINT_PTR>(choices_), menu_label)) {
            if (choices_) DestroyMenu(choices_);
            if (bar_) DestroyMenu(bar_);
            bar_ = choices_ = nullptr;
            LOG("window: could not create the resolution menu");
            return;
        }

        if (!AppendMenuW(choices_, MF_STRING, first_command, scale_labels[0]) ||
            !AppendMenuW(choices_, MF_STRING, first_command + 1, scale_labels[1]) ||
            !AppendMenuW(choices_, MF_STRING, first_command + 2, scale_labels[2]) ||
            !SetWindowSubclass(hwnd_, window_proc, subclass_id, reinterpret_cast<DWORD_PTR>(this))) {
            DestroyMenu(bar_);
            bar_ = choices_ = nullptr;
            LOG("window: could not install the resolution menu");
            return;
        }
        MENUITEMINFOW title{sizeof title};
        title.fMask = MIIM_FTYPE | MIIM_DATA;
        title.fType = MFT_OWNERDRAW;
        title.dwItemData = reinterpret_cast<ULONG_PTR>(this);
        SetMenuItemInfoW(bar_, 0, TRUE, &title);
        for (UINT i = 0; i < 3; ++i) SetMenuItemInfoW(choices_, i, TRUE, &title);
        update_theme();
        update_checks();
    }

    ~ResolutionMenu() {
        if (!bar_) return;
        if (IsWindow(hwnd_)) {
            RemoveWindowSubclass(hwnd_, window_proc, subclass_id);
            set_visible(false);
        }
        DestroyMenu(bar_);
        if (menu_brush_) DeleteObject(menu_brush_);
        if (menu_font_) DeleteObject(menu_font_);
    }

    ResolutionMenu(const ResolutionMenu &) = delete;
    ResolutionMenu &operator=(const ResolutionMenu &) = delete;

    void set_visible(bool visible) const {
        if (!bar_) return;
        const HMENU menu = visible ? bar_ : nullptr;
        if (GetMenu(hwnd_) != menu && SetMenu(hwnd_, menu)) DrawMenuBar(hwnd_);
    }

private:
    static constexpr UINT_PTR subclass_id = 1;
    static constexpr UINT first_command = 0x5100;
    static constexpr int scales[] = {1, 2, 4};
    static constexpr const wchar_t *scale_labels[] = {L"1\u00d7", L"2\u00d7", L"4\u00d7"};
    static constexpr wchar_t menu_label[] = L"&Upscaling";

    static bool is_choice(UINT item) { return item >= first_command && item < first_command + 3; }
    static const wchar_t *item_label(UINT item) {
        return is_choice(item) ? scale_labels[item - first_command] : menu_label;
    }

    void update_theme() {
        HIGHCONTRASTW contrast{sizeof contrast};
        const bool high_contrast = SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof contrast, &contrast, 0) &&
                                   (contrast.dwFlags & HCF_HIGHCONTRASTON);
        BOOL dark = FALSE;
        if (FAILED(DwmGetWindowAttribute(hwnd_, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof dark)))
            dark = SDL_GetSystemTheme() == SDL_SYSTEM_THEME_DARK;

        // Apply one solid color to the caption and menu strip, including when inactive.
        const COLORREF background = high_contrast ? GetSysColor(COLOR_ACTIVECAPTION)
                                  : dark ? RGB(32, 32, 32) : RGB(243, 243, 243);
        const COLORREF foreground = high_contrast ? GetSysColor(COLOR_CAPTIONTEXT)
                                  : dark ? RGB(255, 255, 255) : RGB(22, 22, 22);
        const COLORREF caption = high_contrast ? DWMWA_COLOR_DEFAULT : background;
        const COLORREF text = high_contrast ? DWMWA_COLOR_DEFAULT : foreground;
        DwmSetWindowAttribute(hwnd_, DWMWA_CAPTION_COLOR, &caption, sizeof caption);
        DwmSetWindowAttribute(hwnd_, DWMWA_TEXT_COLOR, &text, sizeof text);

        if (HBRUSH brush = CreateSolidBrush(background)) {
            MENUINFO info{sizeof info};
            info.fMask = MIM_BACKGROUND | MIM_APPLYTOSUBMENUS;
            info.hbrBack = brush;
            if (SetMenuInfo(bar_, &info)) {
                if (menu_brush_) DeleteObject(menu_brush_);
                menu_brush_ = brush;
                menu_text_ = foreground;
            } else {
                DeleteObject(brush);
            }
        }
        dpi_ = GetDpiForWindow(hwnd_);
        if (!dpi_) dpi_ = USER_DEFAULT_SCREEN_DPI;
        NONCLIENTMETRICSW metrics{sizeof metrics};
        if (SystemParametersInfoForDpi(SPI_GETNONCLIENTMETRICS, sizeof metrics, &metrics, 0, dpi_)) {
            if (HFONT font = CreateFontIndirectW(&metrics.lfMenuFont)) {
                if (menu_font_) DeleteObject(menu_font_);
                menu_font_ = font;
            }
        }
        if (GetMenu(hwnd_) == bar_) DrawMenuBar(hwnd_);
    }

    void measure_item(MEASUREITEMSTRUCT &item) const {
        RECT bounds{};
        if (HDC dc = GetDC(hwnd_)) {
            const HGDIOBJ previous_font = menu_font_ ? SelectObject(dc, menu_font_) : nullptr;
            DrawTextW(dc, item_label(item.itemID), -1, &bounds, DT_SINGLELINE | DT_CALCRECT);
            if (previous_font) SelectObject(dc, previous_font);
            ReleaseDC(hwnd_, dc);
        }
        const int padding = is_choice(item.itemID) ? 44 : 20;
        item.itemWidth = (bounds.right - bounds.left) + MulDiv(padding, dpi_, USER_DEFAULT_SCREEN_DPI);
        item.itemHeight = (bounds.bottom - bounds.top) + MulDiv(6, dpi_, USER_DEFAULT_SCREEN_DPI);
    }

    void draw_item(const DRAWITEMSTRUCT &item) const {
        const bool selected = item.itemState & (ODS_SELECTED | ODS_HOTLIGHT);
        HBRUSH brush = selected ? GetSysColorBrush(COLOR_HIGHLIGHT) : menu_brush_;
        FillRect(item.hDC, &item.rcItem, brush ? brush : GetSysColorBrush(COLOR_MENUBAR));
        const HGDIOBJ previous_font = menu_font_ ? SelectObject(item.hDC, menu_font_) : nullptr;
        const int previous_mode = SetBkMode(item.hDC, TRANSPARENT);
        const COLORREF previous_color = SetTextColor(item.hDC, selected ? GetSysColor(COLOR_HIGHLIGHTTEXT) : menu_text_);
        RECT text = item.rcItem;
        UINT flags = DT_CENTER | DT_VCENTER | DT_SINGLELINE;
        if (is_choice(item.itemID)) {
            text.left += MulDiv(8, dpi_, USER_DEFAULT_SCREEN_DPI);
            if (item.itemState & ODS_CHECKED)
                DrawTextW(item.hDC, L"\u2713", -1, &text, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            text.left += MulDiv(24, dpi_, USER_DEFAULT_SCREEN_DPI);
            flags = DT_LEFT | DT_VCENTER | DT_SINGLELINE;
        }
        if (item.itemState & ODS_NOACCEL) flags |= DT_HIDEPREFIX;
        DrawTextW(item.hDC, item_label(item.itemID), -1, &text, flags);
        SetTextColor(item.hDC, previous_color);
        SetBkMode(item.hDC, previous_mode);
        if (previous_font) SelectObject(item.hDC, previous_font);
    }

    void update_checks() const {
        for (UINT i = 0; i < 3; ++i) {
            CheckMenuItem(choices_, first_command + i,
                          MF_BYCOMMAND | (scales[i] == settings_.resolution ? MF_CHECKED : MF_UNCHECKED));
        }
    }

    static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam,
                                        UINT_PTR, DWORD_PTR data) {
        auto &menu = *reinterpret_cast<ResolutionMenu *>(data);
        switch (message) {
        case WM_MEASUREITEM: {
            auto &item = *reinterpret_cast<MEASUREITEMSTRUCT *>(lparam);
            if (item.CtlType == ODT_MENU && item.itemData == data) {
                menu.measure_item(item);
                return TRUE;
            }
            break;
        }
        case WM_DRAWITEM: {
            const auto &item = *reinterpret_cast<const DRAWITEMSTRUCT *>(lparam);
            if (item.CtlType == ODT_MENU && item.itemData == data) {
                menu.draw_item(item);
                return TRUE;
            }
            break;
        }
        case WM_MENUCHAR:
            if (reinterpret_cast<HMENU>(lparam) == menu.bar_ && (LOWORD(wparam) == L'u' || LOWORD(wparam) == L'U'))
                return MAKELRESULT(0, MNC_EXECUTE);
            break;
        case WM_SETTINGCHANGE:
        case WM_THEMECHANGED:
        case WM_SYSCOLORCHANGE:
        case WM_DPICHANGED: {
            const LRESULT result = DefSubclassProc(hwnd, message, wparam, lparam);
            menu.update_theme();
            return result;
        }
        }
        if (message == WM_COMMAND && HIWORD(wparam) == 0 && lparam == 0) {
            const UINT command = LOWORD(wparam);
            if (is_choice(command)) {
                const int scale = scales[command - first_command];
                if (menu.settings_.resolution != scale) {
                    menu.settings_.resolution = scale;
                    pica::set_resolution_scale(scale);
                    menu.settings_.save();
                    menu.update_checks();
                    LOG("graphics: resolution set to %dx", scale);
                }
                return 0;
            }
        }
        return DefSubclassProc(hwnd, message, wparam, lparam);
    }

    Settings &settings_;
    HWND hwnd_ = nullptr;
    HMENU bar_ = nullptr;
    HMENU choices_ = nullptr;
    HBRUSH menu_brush_ = nullptr;
    HFONT menu_font_ = nullptr;
    COLORREF menu_text_ = GetSysColor(COLOR_MENUTEXT);
    UINT dpi_ = USER_DEFAULT_SCREEN_DPI;
};

} // namespace frontend
