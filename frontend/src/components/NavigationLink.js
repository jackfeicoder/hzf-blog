import { createElement } from 'react'
import { NavLink } from 'react-router-dom'

// External tools are not application routes and must never inherit active state.
export default function NavigationLink({ item, children, ...props }) {
  return item.external
    ? createElement('a', { ...props, href: item.to, target: '_blank', rel: 'noopener noreferrer' }, children)
    : createElement(NavLink, { ...props, to: item.to, end: item.end }, children)
}
