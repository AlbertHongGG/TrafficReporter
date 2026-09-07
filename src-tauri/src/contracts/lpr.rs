macro_rules! impl_enum_as_str_and_display {
    ($enum_type:ident { $($variant:ident => $str_val:literal),+ $(,)? }) => {
        impl $enum_type {
            pub fn as_str(&self) -> &'static str {
                match self {
                    $(Self::$variant => $str_val,)+
                }
            }

            pub fn from_str_opt(s: &str) -> Option<Self> {
                match s {
                    $($str_val => Some(Self::$variant),)+
                    _ => None,
                }
            }
        }
        impl std::fmt::Display for $enum_type {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "{}", self.as_str())
            }
        }
    };
}

#[path = "lpr_common.rs"]
pub mod lpr_common;
#[path = "lpr_workspace.rs"]
pub mod lpr_workspace;
#[path = "lpr_media.rs"]
pub mod lpr_media;
#[path = "lpr_export.rs"]
pub mod lpr_export;
#[path = "lpr_ai.rs"]
pub mod lpr_ai;

pub use lpr_common::*;
pub use lpr_workspace::*;
pub use lpr_media::*;
pub use lpr_export::*;
pub use lpr_ai::*;
