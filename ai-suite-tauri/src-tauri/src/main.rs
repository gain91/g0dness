// Prevents console window on Windows
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ai_suite_lib::run();
}
