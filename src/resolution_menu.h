#pragma once

#include <SDL3/SDL.h>
#include <windows.h>
#include <commctrl.h>
#include <dwmapi.h>
#include <cwctype>
#include <cwchar>

// The Windows SDK defines this name as a macro. The SDL layout uses it as a local variable.
#undef small

#include "frontend/settings.h"
#include "log.h"
#include "video/pica.h"
#include "video/gpu/gpu.h"

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

        aspects_ = CreatePopupMenu();
        if (!aspects_ || !AppendMenuW(bar_, MF_POPUP, reinterpret_cast<UINT_PTR>(aspects_), aspect_title())) {
            if (aspects_) DestroyMenu(aspects_);
            DestroyMenu(bar_);
            bar_ = choices_ = aspects_ = nullptr;
            LOG("window: could not create the aspect ratio menu");
            return;
        }

        if (!AppendMenuW(choices_, MF_STRING, first_command, scale_labels[0]) ||
            !AppendMenuW(choices_, MF_STRING, first_command + 1, scale_labels[1]) ||
            !AppendMenuW(choices_, MF_STRING, first_command + 2, scale_labels[2]) ||
            !AppendMenuW(aspects_, MF_STRING, first_aspect, original_label()) ||
            !AppendMenuW(aspects_, MF_STRING, first_aspect + 1, L"16:9") ||
            !AppendMenuW(aspects_, MF_STRING, first_aspect + 2, ultrawide_label()) ||
            !SetWindowSubclass(hwnd_, window_proc, subclass_id, reinterpret_cast<DWORD_PTR>(this))) {
            DestroyMenu(bar_);
            bar_ = choices_ = aspects_ = nullptr;
            LOG("window: could not install the resolution menu");
            return;
        }
        MENUITEMINFOW title{sizeof title};
        title.fMask = MIIM_FTYPE | MIIM_DATA;
        title.fType = MFT_OWNERDRAW;
        title.dwItemData = reinterpret_cast<ULONG_PTR>(this);
        for (UINT i = 0; i < 2; ++i) {
            title.fMask |= MIIM_ID;
            title.wID = first_title + i;
            SetMenuItemInfoW(bar_, i, TRUE, &title);
        }
        title.fMask &= ~MIIM_ID;
        for (UINT i = 0; i < 3; ++i) {
            SetMenuItemInfoW(choices_, i, TRUE, &title);
            SetMenuItemInfoW(aspects_, i, TRUE, &title);
        }
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
    static constexpr UINT first_aspect = 0x5110;
    static constexpr UINT first_title = 0x5120;
    static constexpr int scales[] = {1, 2, 4};
    static constexpr const wchar_t *scale_labels[] = {L"1\u00d7", L"2\u00d7", L"4\u00d7"};
    static constexpr wchar_t menu_label[] = L"&Upscaling";

    static bool is_scale(UINT item) { return item >= first_command && item < first_command + 3; }
    static bool is_aspect(UINT item) { return item >= first_aspect && item < first_aspect + 3; }
    static bool is_choice(UINT item) { return is_scale(item) || is_aspect(item); }

    const wchar_t *aspect_title() const {
        switch (settings_.language) {
        case 2: return L"&Format d'image";
        case 3: return L"&Bildformat";
        case 4: return L"&Formato immagine";
        case 5: return L"&Relaci\u00f3n de aspecto";
        case 8: return L"&Beeldverhouding";
        case 9: return L"&Propor\u00e7\u00e3o da imagem";
        case 10: return L"&\u0421\u043e\u043e\u0442\u043d\u043e\u0448\u0435\u043d\u0438\u0435 \u0441\u0442\u043e\u0440\u043e\u043d";
        default: return L"&Aspect ratio";
        }
    }

    const wchar_t *original_label() const {
        switch (settings_.language) {
        case 4: return L"Originale (5:3)";
        case 8: return L"Origineel (5:3)";
        case 10: return L"\u0418\u0441\u0445\u043e\u0434\u043d\u044b\u0439 (5:3)";
        default: return L"Original (5:3)";
        }
    }

    const wchar_t *ultrawide_label() const {
        switch (settings_.language) {
        case 2: return L"21:9 (exp\u00e9rimental)";
        case 3: return L"21:9 (experimentell)";
        case 4: return L"21:9 (sperimentale)";
        case 8: return L"21:9 (experimenteel)";
        case 10: return L"21:9 (\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430\u043b\u044c\u043d\u043e)";
        default: return L"21:9 (experimental)";
        }
    }

    const wchar_t *item_label(UINT item) const {
        if (is_scale(item)) return scale_labels[item - first_command];
        if (is_aspect(item)) {
            if (item == first_aspect) return original_label();
            return item == first_aspect + 1 ? L"16:9" : ultrawide_label();
        }
        return item == first_title ? menu_label : aspect_title();
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
        const bool disabled = item.itemState & (ODS_DISABLED | ODS_GRAYED);
        const COLORREF text_color = disabled ? GetSysColor(COLOR_GRAYTEXT)
                                            : selected ? GetSysColor(COLOR_HIGHLIGHTTEXT) : menu_text_;
        const COLORREF previous_color = SetTextColor(item.hDC, text_color);
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
        const bool wide_available = pica::gpu::active();
        const int active_aspect = wide_available ? settings_.aspect_ratio : 0;
        for (UINT i = 0; i < 3; ++i) {
            CheckMenuItem(choices_, first_command + i,
                          MF_BYCOMMAND | (scales[i] == settings_.resolution ? MF_CHECKED : MF_UNCHECKED));
            CheckMenuItem(aspects_, first_aspect + i,
                          MF_BYCOMMAND | (int(i) == active_aspect ? MF_CHECKED : MF_UNCHECKED));
            EnableMenuItem(aspects_, first_aspect + i,
                           MF_BYCOMMAND | (i == 0 || wide_available ? MF_ENABLED : MF_GRAYED));
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
        case WM_INITMENUPOPUP:
            menu.update_checks();
            break;
        case WM_MENUCHAR:
            if (reinterpret_cast<HMENU>(lparam) == menu.bar_) {
                for (UINT i = 0; i < 2; ++i) {
                    const wchar_t *label = menu.item_label(first_title + i);
                    const wchar_t *accelerator = std::wcschr(label, L'&');
                    if (accelerator && std::towlower(accelerator[1]) == std::towlower(LOWORD(wparam)))
                        return MAKELRESULT(i, MNC_EXECUTE);
                }
            }
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
            if (is_scale(command)) {
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
            if (is_aspect(command)) {
                if (command != first_aspect && !pica::gpu::active()) return 0;
                menu.settings_.aspect_ratio = int(command - first_aspect);
                menu.settings_.widescreen = menu.settings_.aspect_ratio != 0;
                pica::set_aspect_ratio(menu.settings_.aspect_ratio);
                menu.settings_.save();
                menu.update_checks();
                LOG("graphics: aspect ratio set to %d", menu.settings_.aspect_ratio);
                return 0;
            }
        }
        return DefSubclassProc(hwnd, message, wparam, lparam);
    }

    Settings &settings_;
    HWND hwnd_ = nullptr;
    HMENU bar_ = nullptr;
    HMENU choices_ = nullptr;
    HMENU aspects_ = nullptr;
    HBRUSH menu_brush_ = nullptr;
    HFONT menu_font_ = nullptr;
    COLORREF menu_text_ = GetSysColor(COLOR_MENUTEXT);
    UINT dpi_ = USER_DEFAULT_SCREEN_DPI;
};

} // namespace frontend
