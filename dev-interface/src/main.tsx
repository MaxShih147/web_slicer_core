import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// 刻意不用 React.StrictMode。
// StrictMode 在開發模式會把 effect 掛載跑兩次，那會建立兩個 WebGL context，
// 對這個以 three.js 為主的工具只有干擾，沒有好處。
ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  React.createElement(App),
)
