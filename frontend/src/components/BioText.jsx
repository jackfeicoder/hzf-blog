import { bioParts } from '../bioLinks'
import './bio-text.css'

export default function BioText({ text }) {
  return bioParts(text).map((part, index) => part.href
    ? <a key={index} href={part.href} target="_blank" rel="noopener noreferrer">{part.text}</a>
    : <span key={index}>{part.text}</span>)
}
