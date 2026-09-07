fn main() {
    let out_path = if std::path::Path::new("src-tauri").exists() {
        "src/domain/ipc/bindings.ts"
    } else {
        "../src/domain/ipc/bindings.ts"
    };

    app_lib::create_builder()
        .export(
            specta_typescript::Typescript::default(),
            out_path,
        )
        .expect("Failed to export specta types");
}
