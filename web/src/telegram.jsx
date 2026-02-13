import { useEffect, useRef } from 'react'

export function TelegramLoginButton({ onAuth }) {
  const ref = useRef(null)

  useEffect(() => {
    const botUsername = import.meta.env.VITE_TG_BOT_USERNAME || 'OscarCRM_bot'
    if (!botUsername || !ref.current) {
      return undefined
    }

    window.onTelegramAuth = (user) => {
      onAuth(user)
    }

    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.setAttribute('data-telegram-login', botUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    script.setAttribute('data-request-access', 'write')
    script.async = true

    ref.current.innerHTML = ''
    ref.current.appendChild(script)

    return () => {
      if (ref.current) {
        ref.current.innerHTML = ''
      }
      delete window.onTelegramAuth
    }
  }, [onAuth])

  return (
    <div className="telegram-login">
      <div ref={ref} />
    </div>
  )
}
