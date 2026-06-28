type ToastIcon = 'success' | 'error' | 'none' | 'loading';

interface ToastOptions {
  title: string;
  icon?: ToastIcon;
  duration?: number;
}

export function showToast(options: string | ToastOptions): void {
  if (typeof options === 'string') {
    options = { title: options, icon: 'none' };
  }
  // Minimal toast: uses native browser alert for now.
  // Replace with a proper toast library (e.g. react-hot-toast) when View layer is built.
  if (options.icon === 'none' || !options.icon) {
    // eslint-disable-next-line no-console
    console.log(`[toast] ${options.title}`);
  } else {
    // eslint-disable-next-line no-console
    console.log(`[toast:${options.icon}] ${options.title}`);
  }
}

export function showLoading(title: string): void {
  // eslint-disable-next-line no-console
  console.log(`[loading] ${title}`);
}

export function hideLoading(): void {
  // no-op until View layer is ready
}

export function showModal(options: {
  title?: string;
  content: string;
  confirmColor?: string;
}): Promise<{ confirm: boolean; cancel: boolean }> {
  const confirmed = window.confirm(`${options.title ? options.title + '\n\n' : ''}${options.content}`);
  return Promise.resolve({ confirm: confirmed, cancel: !confirmed });
}
