// Hub re-export: process-lifecycle vs protocol-framing vs status split.
// Caller paths (e.g. `crate::infrastructure::python_client::invoke_lpr_runtime`) are unchanged.
pub mod process_lifecycle;
pub mod protocol;
pub mod status;

pub(crate) use status::{
    invoke_lpr_runtime, invoke_lpr_runtime_with_progress, terminate_lpr_runtime_process,
};
